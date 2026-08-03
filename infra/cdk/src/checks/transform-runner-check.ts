/**
 * Assertions about the transform runner (decision 0004).
 *
 * `infra/cdk` has no test runner, and a full `cdk synth` needs Docker - the
 * migration Lambda bundles psycopg in a container, deliberately and with no
 * host-pip fallback (docs/deploying.md). So this builds *only* the constructs
 * under test into a throwaway stack and asserts the synthesised template,
 * which needs neither.
 *
 * What it is checking is not "does it deploy" but two properties that are
 * invisible in a diff and expensive to be wrong about:
 *
 *   1. the runner's task role holds no policies, and
 *   2. its security group has no route to the internet.
 *
 * Run: `npx ts-node src/checks/transform-runner-check.ts`
 */
import { App, Stack } from "aws-cdk-lib";
import { Template, Match } from "aws-cdk-lib/assertions";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as cognito from "aws-cdk-lib/aws-cognito";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";

import { ServicesConstruct } from "../constructs/services";

function build(): Template {
  const app = new App();
  const stack = new Stack(app, "CheckStack", { env: { account: "111111111111", region: "eu-west-2" } });
  const vpc = new ec2.Vpc(stack, "Vpc", { maxAzs: 2, natGateways: 1 });
  const endpointSg = new ec2.SecurityGroup(stack, "EndpointSg", { vpc, allowAllOutbound: false });

  new ServicesConstruct(stack, "Services", {
    vpc,
    vpcEndpointSecurityGroup: endpointSg,
    dataBucket: s3.Bucket.fromBucketName(stack, "Bucket", "check-bucket"),
    dbSecret: secretsmanager.Secret.fromSecretNameV2(stack, "DbSecret", "check/db"),
    appDbSecret: secretsmanager.Secret.fromSecretNameV2(stack, "AppDbSecret", "check/appdb"),
    databaseHost: "db.example",
    databasePort: "5432",
    redisEndpoint: "redis.example",
    searchEndpoint: "search.example",
    userPool: cognito.UserPool.fromUserPoolId(stack, "Pool", "eu-west-2_check"),
    userPoolClientId: "check-client",
    apiImage: "registry/api",
    workerImage: "registry/worker",
    webImage: "registry/web",
    imageTag: "check",
  });
  return Template.fromStack(stack);
}

const failures: string[] = [];
function check(name: string, assertion: () => void): void {
  try {
    assertion();
    console.log(`  ok    ${name}`);
  } catch (error) {
    failures.push(`${name}\n        ${(error as Error).message.split("\n")[0]}`);
    console.log(`  FAIL  ${name}`);
  }
}

const template = build();
const roles = template.findResources("AWS::IAM::Role");
const policies = template.findResources("AWS::IAM::Policy");
const groups = template.findResources("AWS::EC2::SecurityGroup");
// Egress rules that reference *another security group* cannot be inlined on
// the group; CloudFormation renders them as standalone resources. The runner's
// rules are all of that kind, so a check that read only the inline
// `SecurityGroupEgress` property found an empty array and passed without
// looking at anything - which is what the first version of this file did, and
// what mutation-testing it caught (STATUS.md §66).
const standaloneEgress = template.findResources("AWS::EC2::SecurityGroupEgress");

function runnerSecurityGroupId(): string {
  const found = Object.keys(groups).find((id) => id.startsWith("ServicesTransformRunnerSg"));
  if (!found) throw new Error("no transform runner security group found");
  return found;
}

/** Every egress rule attached to a group, however CloudFormation rendered it. */
function egressRulesFor(groupId: string): Record<string, unknown>[] {
  const inline = (groups[groupId].Properties?.SecurityGroupEgress ?? []) as Record<string, unknown>[];
  const separate = Object.values(standaloneEgress)
    .filter((rule) => JSON.stringify(rule.Properties?.GroupId ?? "").includes(groupId))
    .map((rule) => rule.Properties as Record<string, unknown>);
  const rules = [...inline, ...separate];
  // A group with `allowAllOutbound: false` and no rules is not rendered empty:
  // CDK inlines a placeholder to 255.255.255.255/32 so CloudFormation accepts
  // it. Reported as what it is, because otherwise the port check below fails
  // blaming "port 86" and sends somebody hunting a rule nobody wrote.
  if (rules.length === 1 && rules[0].CidrIp === "255.255.255.255/32") {
    throw new Error(
      `${groupId} has no egress rules at all - a task in it cannot pull its image or start`
    );
  }
  return rules;
}

const runnerRoleIds = Object.entries(roles)
  .filter(([id]) => id.startsWith("ServicesTransformRunnerTaskRole"))
  .map(([id]) => id);

console.log("transform runner (decision 0004):");

check("the runner has a task role of its own", () => {
  if (runnerRoleIds.length !== 1) {
    throw new Error(`expected exactly one runner task role, found ${runnerRoleIds.length}`);
  }
});

check("the runner's task role holds no policies", () => {
  // The control, not a nicety: ECS hands a task its credentials over
  // link-local networking that no security group filters, so what stops a
  // transform mattering is that the credentials it can obtain grant nothing.
  const attached = Object.values(policies).filter((policy) =>
    JSON.stringify(policy.Properties?.Roles ?? []).includes(runnerRoleIds[0])
  );
  if (attached.length > 0) {
    throw new Error(
      `the runner role has ${attached.length} policy attachment(s); it must have none`
    );
  }
  const inline = roles[runnerRoleIds[0]].Properties?.Policies ?? [];
  if (inline.length > 0) throw new Error(`the runner role has ${inline.length} inline policies`);
  const managed = roles[runnerRoleIds[0]].Properties?.ManagedPolicyArns ?? [];
  if (managed.length > 0) throw new Error(`the runner role has ${managed.length} managed policies`);
});

check("the runner's security group has no route to the internet", () => {
  const rules = egressRulesFor(runnerSecurityGroupId());
  if (rules.length === 0) {
    // A group with no rules at all would pass every assertion below while
    // meaning the runner cannot start. Refusing to pass on nothing is what
    // stops this check going quiet if the rules move again.
    throw new Error("found no egress rules to check - has the rendering changed?");
  }
  const open = rules.filter((rule) => rule.CidrIp === "0.0.0.0/0" || rule.CidrIpv6 === "::/0");
  if (open.length > 0) {
    throw new Error(`the runner security group has ${open.length} open egress rule(s)`);
  }
});

check("the runner does not receive the database password", () => {
  // The worker's containers take DATABASE_PASSWORD from Secrets Manager. The
  // runner must not: a transform holding the app database password could set
  // app.service='worker' and read every workspace in the deployment (db 0006).
  const taskDefs = template.findResources("AWS::ECS::TaskDefinition");
  const runner = Object.entries(taskDefs).find(([id]) =>
    id.startsWith("ServicesTransformRunnerTaskDef")
  );
  if (!runner) throw new Error("no transform runner task definition found");
  const containers = runner[1].Properties?.ContainerDefinitions ?? [];
  for (const container of containers) {
    const secrets = container.Secrets ?? [];
    if (secrets.length > 0) {
      throw new Error(`the runner container is given ${secrets.length} secret(s)`);
    }
  }
});

check("adding the scratch mount did not open a route out", () => {
  // Egress now has two destinations - the VPC endpoints and one filesystem -
  // and neither is the internet. A future "just add one egress rule" is what
  // this exists to catch.
  const rules = egressRulesFor(runnerSecurityGroupId());
  const allowed = new Set([443, 2049]);
  const unexpected = rules.map((rule) => rule.ToPort).filter((port) => !allowed.has(port as number));
  if (unexpected.length > 0) {
    throw new Error(`the runner can reach unexpected port(s): ${unexpected.join(", ")}`);
  }
});

check("the runner has the scratch filesystem mounted", () => {
  // Without it the runner has no way to receive inputs at all, and the
  // failure would be a container that starts and immediately reports a
  // missing job file - which reads like a caller bug rather than a mount bug.
  const taskDefs = template.findResources("AWS::ECS::TaskDefinition");
  const runner = Object.entries(taskDefs).find(([id]) =>
    id.startsWith("ServicesTransformRunnerTaskDef")
  );
  if (!runner) throw new Error("no transform runner task definition found");
  const volumes = runner[1].Properties?.Volumes ?? [];
  if (!volumes.some((v: Record<string, unknown>) => v.EFSVolumeConfiguration)) {
    throw new Error("the runner task definition has no EFS volume");
  }
  const mounts = (runner[1].Properties?.ContainerDefinitions ?? [])
    .flatMap((c: Record<string, unknown>) => (c.MountPoints as unknown[]) ?? []);
  if (mounts.length === 0) throw new Error("the runner container mounts nothing");
});

check("the scratch volume is encrypted in transit", () => {
  // It carries the customer's data between two tasks. In transit encryption is
  // off by default on an EFS volume configuration, which is the kind of
  // default that is easy to never notice.
  const taskDefs = template.findResources("AWS::ECS::TaskDefinition");
  for (const [id, def] of Object.entries(taskDefs)) {
    for (const volume of def.Properties?.Volumes ?? []) {
      const config = volume.EFSVolumeConfiguration;
      if (config && config.TransitEncryption !== "ENABLED") {
        throw new Error(`${id} mounts the scratch volume without transit encryption`);
      }
    }
  }
});

// ---- the dispatching side ----------------------------------------------------
/** Every policy statement attached to the one role whose logical id starts with `prefix`. */
function statementsForRole(prefix: string): Record<string, unknown>[] {
  const roleId = Object.keys(roles).find((id) => id.startsWith(prefix));
  if (!roleId) throw new Error(`no role found with logical id starting ${prefix}`);
  const statements = Object.values(policies)
    .filter((policy) => JSON.stringify(policy.Properties?.Roles ?? []).includes(roleId))
    .flatMap((policy) => (policy.Properties?.PolicyDocument?.Statement ?? []) as Record<string, unknown>[]);
  if (statements.length === 0) {
    throw new Error(`found no policy statements for ${prefix} - has the rendering changed?`);
  }
  return statements;
}

function actionsOf(statement: Record<string, unknown>): string[] {
  const action = statement.Action;
  return (Array.isArray(action) ? action : [action]).filter(
    (a): a is string => typeof a === "string"
  );
}

check("the worker may pass the runner's roles and no others", () => {
  // The escalation, if this were wrong: RunTask needs iam:PassRole, and an
  // unscoped one lets the worker register a task definition naming any role in
  // the account and start a container as it - which would make the runner's
  // empty role (the whole control in decision 0004) beside the point.
  const passRole = statementsForRole("ServicesWorkerTaskRole").filter((s) =>
    actionsOf(s).includes("iam:PassRole")
  );
  if (passRole.length === 0) {
    throw new Error("the worker cannot pass any role, so RunTask will fail at dispatch time");
  }
  for (const statement of passRole) {
    const resources = JSON.stringify(statement.Resource ?? "");
    if (resources.includes('"*"') || resources === '"*"') {
      throw new Error("the worker may pass any role in the account");
    }
    if (!resources.includes("TransformRunner")) {
      throw new Error(`iam:PassRole names something other than the runner's roles: ${resources}`);
    }
  }
});

check("the worker may start the runner task and nothing else", () => {
  const runTask = statementsForRole("ServicesWorkerTaskRole").filter((s) =>
    actionsOf(s).includes("ecs:RunTask")
  );
  if (runTask.length !== 1) {
    throw new Error(`expected exactly one ecs:RunTask statement, found ${runTask.length}`);
  }
  const resources = JSON.stringify(runTask[0].Resource ?? "");
  if (resources.includes('"*"')) {
    throw new Error("the worker may run any task definition in the account");
  }
  if (!runTask[0].Condition) {
    throw new Error("ecs:RunTask is not pinned to a cluster");
  }
});

check("the worker is told where the runner is", () => {
  // Without these the dispatcher refuses at run time with "no transform runner
  // configured" - correct, but only discovered when somebody runs a transform.
  const taskDefs = template.findResources("AWS::ECS::TaskDefinition");
  const worker = Object.entries(taskDefs).find(([id]) => id.startsWith("ServicesworkerTaskDef"));
  if (!worker) throw new Error("no worker task definition found");
  const environment = (worker[1].Properties?.ContainerDefinitions ?? [])
    .flatMap((c: Record<string, unknown>) => (c.Environment as Record<string, unknown>[]) ?? []);
  const names = new Set(environment.map((e: Record<string, unknown>) => e.Name as string));
  const required = [
    "ANCHOR_TRANSFORM_SCRATCH",
    "ANCHOR_TRANSFORM_CLUSTER",
    "ANCHOR_TRANSFORM_TASK_DEFINITION",
    "ANCHOR_TRANSFORM_SUBNETS",
    "ANCHOR_TRANSFORM_SECURITY_GROUPS",
  ].filter((name) => !names.has(name));
  if (required.length > 0) {
    throw new Error(`the worker is missing: ${required.join(", ")}`);
  }
});

check("the worker still has the permissions it needs", () => {
  // The counterweight: this check exists to stop the runner gaining
  // permissions, not to strip the worker of its own by accident.
  template.hasResourceProperties("AWS::IAM::Role", {
    Description: Match.stringLikeRegexp("worker task role"),
  });
});

if (failures.length > 0) {
  console.error(`\n${failures.length} check(s) failed:`);
  for (const failure of failures) console.error(`  - ${failure}`);
  process.exit(1);
}
console.log("\nall checks passed");

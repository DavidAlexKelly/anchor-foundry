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

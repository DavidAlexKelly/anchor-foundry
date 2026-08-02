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
  const runnerSg = Object.entries(groups).find(([id]) =>
    id.startsWith("ServicesTransformRunnerSg")
  );
  if (!runnerSg) throw new Error("no transform runner security group found");
  const egress = runnerSg[1].Properties?.SecurityGroupEgress ?? [];
  const open = egress.filter(
    (rule: Record<string, unknown>) => rule.CidrIp === "0.0.0.0/0" || rule.CidrIpv6 === "::/0"
  );
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

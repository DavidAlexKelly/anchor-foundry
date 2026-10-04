/**
 * Assertions about where a stack's objects live (§814).
 *
 * The API and the worker read objects from OpenSearch when both
 * `OPENSEARCH_ENDPOINT` and `OPENSEARCH_SECRET_ARN` are set, and from Postgres
 * otherwise. Stacks set the endpoint and never the secret, so every deployment
 * ran on Postgres and the domain sat unused. The `objectStore` context flag
 * turns the index on. These are the properties that matter about it and that
 * no diff shows:
 *
 *   1. off by default, entirely: no secret handed out, no policy opened;
 *   2. on, both object services get the domain's master secret and may read
 *      it, and the web service gets neither;
 *   3. on, the domain's policy lets basic-auth requests through to
 *      fine-grained access control, which otherwise never sees them;
 *   4. the secret is the `{username, password}` the services parse.
 *
 * Like transform-runner-check.ts, this builds only the constructs under test,
 * because a full synth needs Docker.
 *
 * Run: `npx ts-node src/checks/object-store-check.ts`
 */
import * as fs from "fs";
import * as path from "path";

import { App, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as cognito from "aws-cdk-lib/aws-cognito";

import { DataStoresConstruct } from "../constructs/data-stores";
import { ServicesConstruct } from "../constructs/services";

// The deployed app's feature flags, since the constructs under test depend on
// them: without `serverAccessLogsUseBucketPolicy` the data bucket's access
// logging does not synthesise at all.
const context = JSON.parse(
  fs.readFileSync(path.join(__dirname, "..", "..", "cdk.json"), "utf8")
).context;

function build(objectIndex: boolean): Template {
  const app = new App({ context });
  const stack = new Stack(app, "CheckStack", { env: { account: "111111111111", region: "eu-west-2" } });
  const vpc = new ec2.Vpc(stack, "Vpc", { maxAzs: 2, natGateways: 1 });
  const endpointSg = new ec2.SecurityGroup(stack, "EndpointSg", { vpc, allowAllOutbound: false });
  const data = new DataStoresConstruct(stack, "Data", { vpc, orgSlug: "check", objectIndex });
  new ServicesConstruct(stack, "Services", {
    vpc,
    vpcEndpointSecurityGroup: endpointSg,
    dataBucket: data.dataBucket,
    dbSecret: data.dbSecret,
    appDbSecret: data.appDbSecret,
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
    objectIndexSecret: objectIndex ? data.searchMasterSecret : undefined,
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

function masterSecretId(template: Template): string {
  const found = Object.keys(template.findResources("AWS::SecretsManager::Secret")).filter((id) =>
    id.startsWith("DataSearchMasterUser")
  );
  if (found.length !== 1) throw new Error(`expected one domain master secret, found ${found.length}`);
  return found[0];
}

/** Each service's container environment, by service name. */
function environments(template: Template): Record<string, Record<string, unknown>> {
  const out: Record<string, Record<string, unknown>> = {};
  for (const [id, def] of Object.entries(template.findResources("AWS::ECS::TaskDefinition"))) {
    const service = ["api", "worker", "web"].find((name) => id.startsWith(`Services${name}TaskDef`));
    if (!service) continue;
    const env: Record<string, unknown> = {};
    for (const container of def.Properties?.ContainerDefinitions ?? []) {
      for (const pair of container.Environment ?? []) env[pair.Name] = pair.Value;
    }
    out[service] = env;
  }
  for (const name of ["api", "worker", "web"]) {
    if (!out[name]) throw new Error(`no ${name} task definition found`);
  }
  return out;
}

/** The role ids holding a policy statement that names this secret. */
function rolesReading(template: Template, secretId: string): string[] {
  const roles = new Set<string>();
  for (const policy of Object.values(template.findResources("AWS::IAM::Policy"))) {
    const statements = policy.Properties?.PolicyDocument?.Statement ?? [];
    const reads = statements.some(
      (s: Record<string, unknown>) =>
        JSON.stringify(s.Action).includes("secretsmanager:GetSecretValue") &&
        JSON.stringify(s.Resource).includes(secretId)
    );
    if (!reads) continue;
    for (const role of policy.Properties?.Roles ?? []) roles.add(JSON.stringify(role));
  }
  return [...roles];
}

function domain(template: Template): Record<string, unknown> {
  const domains = Object.values(template.findResources("AWS::OpenSearchService::Domain"));
  if (domains.length !== 1) throw new Error(`expected one domain, found ${domains.length}`);
  return domains[0].Properties ?? {};
}

const off = build(false);
const on = build(true);

console.log("object store (§814):");

check("by default no service is told the index's secret", () => {
  for (const [service, env] of Object.entries(environments(off))) {
    if ("OPENSEARCH_SECRET_ARN" in env) throw new Error(`${service} is given OPENSEARCH_SECRET_ARN`);
  }
});

check("by default nothing may read the master secret", () => {
  const readers = rolesReading(off, masterSecretId(off));
  if (readers.length > 0) throw new Error(`${readers.length} role(s) may read it`);
});

check("by default the domain's policy is not opened", () => {
  // CDK renders the policy through a custom resource as well as inline; both
  // are checked, so a change in how it renders cannot pass this by moving.
  if (domain(off).AccessPolicies) throw new Error("the domain has an access policy");
  if (Object.keys(off.findResources("Custom::OpenSearchAccessPolicy")).length > 0) {
    throw new Error("the domain has an access policy resource");
  }
});

check("opted in, the API and the worker are told the master secret", () => {
  const secret = masterSecretId(on);
  const envs = environments(on);
  for (const service of ["api", "worker"]) {
    const value = JSON.stringify(envs[service].OPENSEARCH_SECRET_ARN ?? null);
    if (!value.includes(secret)) throw new Error(`${service}'s OPENSEARCH_SECRET_ARN is ${value}`);
    if (!envs[service].OPENSEARCH_ENDPOINT) throw new Error(`${service} has no OPENSEARCH_ENDPOINT`);
  }
});

check("opted in, the web service is told nothing", () => {
  if ("OPENSEARCH_SECRET_ARN" in environments(on).web) throw new Error("web is given the secret");
});

check("opted in, exactly the API's and the worker's roles may read the secret", () => {
  const readers = rolesReading(on, masterSecretId(on)).sort();
  const expected = ["ServicesApiTaskRole", "ServicesWorkerTaskRole"];
  if (readers.length !== 2 || !expected.every((name, i) => readers[i].includes(name))) {
    throw new Error(`readers: ${readers.join(", ") || "none"}`);
  }
});

check("opted in, the domain lets basic auth through to fine-grained access control", () => {
  // The policy travels as JSON inside an SDK call's JSON inside a template,
  // escaped once per layer; the escapes are dropped before reading it.
  const rendered = JSON.stringify({
    inline: domain(on).AccessPolicies ?? null,
    resource: Object.values(on.findResources("Custom::OpenSearchAccessPolicy")).map(
      (r) => r.Properties
    ),
  }).replace(/\\/g, "");
  for (const needle of ['"Action":"es:ESHttp*"', '"Effect":"Allow"', '"Principal":{"AWS":"*"}']) {
    if (!rendered.includes(needle)) throw new Error(`the domain's policy has no ${needle}`);
  }
});

check("the master secret is the username and password the services read", () => {
  const generated = off.findResources("AWS::SecretsManager::Secret")[masterSecretId(off)]
    .Properties?.GenerateSecretString;
  if (generated?.GenerateStringKey !== "password") {
    throw new Error(`the generated key is ${generated?.GenerateStringKey}`);
  }
  if (JSON.parse(generated.SecretStringTemplate).username !== "platform-admin") {
    throw new Error(`the template is ${generated.SecretStringTemplate}`);
  }
});

if (failures.length > 0) {
  console.log(`\n${failures.length} check(s) failed:\n  ${failures.join("\n  ")}`);
  process.exit(1);
}
console.log("\nall checks passed");

/**
 * Assertions about the whole customer stack, synthesized as `cdk deploy`
 * would (§849).
 *
 * The other checks build one construct each, because a full synth needs
 * Docker for the migration Lambda's package. This one skips bundling - CDK's
 * `aws:cdk:bundling-stacks` context, set to none - and stands a registry image
 * in for the bundling image, which `DockerImage.fromBuild` would otherwise
 * build while the stack is still being constructed. Nothing about bundling is
 * asserted here; `apps/api/tests/test_migration_bundle.py` covers what the
 * package holds.
 *
 * What is checked is where the platform says it is served:
 *
 *   1. the hosted UI sends a viewer back to the distribution's own address,
 *      which is the origin the web app asks for (`apps/web/src/lib/auth.ts`);
 *   2. a custom address, when given, is allowed beside it, not instead;
 *   3. the API is told the same address, for the addresses it hands out;
 *   4. the control plane can read it, with its scheme, as an output;
 *   5. a listener trusts only the X-Forwarded-For entries nobody else can
 *      write, which depends on whether the load balancer is public (§850).
 *
 * Run: `npx ts-node src/checks/stack-check.ts`
 */
import * as fs from "fs";
import * as path from "path";

import { App, DockerImage } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";

import { CustomerStack } from "../stacks/customer-stack";

(DockerImage as unknown as { fromBuild: () => DockerImage }).fromBuild =
  () => DockerImage.fromRegistry("bundling-skipped");

const context = JSON.parse(
  fs.readFileSync(path.join(__dirname, "..", "..", "cdk.json"), "utf8")
).context;

function synth(platformUrl?: string): Template {
  const app = new App({ context: { ...context, "aws:cdk:bundling-stacks": [] } });
  const stack = new CustomerStack(app, "PlatformStack", {
    orgSlug: "check",
    platformUrl,
    vendorEcrRegistry: "111111111111.dkr.ecr.eu-west-2.amazonaws.com",
    imageTag: "check",
    objectStore: "postgres",
    env: { account: "111111111111", region: "eu-west-2" },
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

function only(template: Template, type: string): Record<string, any> {
  const found = Object.values(template.findResources(type));
  if (found.length !== 1) throw new Error(`expected one ${type}, found ${found.length}`);
  return found[0];
}

/** `https://<the distribution's domain><suffix>`, as CloudFormation writes it. */
function servedAt(template: Template, suffix: string): string {
  const id = Object.keys(template.findResources("AWS::CloudFront::Distribution"))[0];
  const parts: unknown[] = ["https://", { "Fn::GetAtt": [id, "DomainName"] }];
  if (suffix) parts.push(suffix);
  return JSON.stringify({ "Fn::Join": ["", parts] });
}

function client(template: Template): Record<string, any> {
  return only(template, "AWS::Cognito::UserPoolClient").Properties;
}

const plain = synth();
const custom = synth("https://data.example.com");

console.log("where the platform is served (§849):");

check("the web app asks to come back to its own origin", () => {
  const auth = fs.readFileSync(
    path.join(__dirname, "..", "..", "..", "..", "apps", "web", "src", "lib", "auth.ts"), "utf8");
  if (!auth.includes("redirectUri: `${window.location.origin}/callback`")) {
    throw new Error("apps/web/src/lib/auth.ts no longer builds its redirect from its origin: re-derive this check");
  }
});

check("the hosted UI sends a viewer back to the distribution's address", () => {
  const { CallbackURLs, LogoutURLs } = client(plain);
  if (JSON.stringify(CallbackURLs) !== `[${servedAt(plain, "/callback")}]`) {
    throw new Error(`callbacks are ${JSON.stringify(CallbackURLs)}`);
  }
  if (JSON.stringify(LogoutURLs) !== `[${servedAt(plain, "/login")}]`) {
    throw new Error(`sign-out returns to ${JSON.stringify(LogoutURLs)}`);
  }
});

check("a custom address is allowed beside it, not instead", () => {
  const { CallbackURLs, LogoutURLs } = client(custom);
  const want = `[${servedAt(custom, "/callback")},"https://data.example.com/callback"]`;
  if (JSON.stringify(CallbackURLs) !== want) throw new Error(`callbacks are ${JSON.stringify(CallbackURLs)}`);
  if (!JSON.stringify(LogoutURLs).includes('"https://data.example.com/login"')) {
    throw new Error(`sign-out returns to ${JSON.stringify(LogoutURLs)}`);
  }
});

check("no placeholder address reaches the template", () => {
  for (const template of [plain, custom]) {
    if (JSON.stringify(template.toJSON()).includes("unset.invalid")) throw new Error("unset.invalid is in it");
  }
});

check("the API is told the same address", () => {
  const defs = Object.entries(plain.findResources("AWS::ECS::TaskDefinition"))
    .map(([, r]) => r.Properties.ContainerDefinitions[0])
    .filter((c) => c.Name === "api");
  if (defs.length !== 1) throw new Error(`expected one api container, found ${defs.length}`);
  const env = (defs[0].Environment as { Name: string; Value: unknown }[])
    .find((e) => e.Name === "PLATFORM_PUBLIC_URL");
  if (!env) throw new Error("the api has no PLATFORM_PUBLIC_URL");
  if (JSON.stringify(env.Value) !== servedAt(plain, "")) throw new Error(`it is ${JSON.stringify(env.Value)}`);
});

check("the control plane can read the address, scheme and all", () => {
  const outputs = plain.toJSON().Outputs ?? {};
  if (JSON.stringify(outputs.PlatformUrl?.Value) !== servedAt(plain, "")) {
    throw new Error(`PlatformUrl is ${JSON.stringify(outputs.PlatformUrl?.Value)}`);
  }
});

console.log("who a listener's allowlist sees (§850):");

check("the proxy hops match how the load balancer is reached", () => {
  // Public, a request can reach the load balancer directly and write every
  // X-Forwarded-For entry left of the load balancer's own: only one hop can
  // be trusted. Internal behind a CloudFront VPC origin (decision 0025), the
  // entry CloudFront writes is the sender's, two from the right.
  const scheme = only(plain, "AWS::ElasticLoadBalancingV2::LoadBalancer").Properties.Scheme;
  const api = Object.values(plain.findResources("AWS::ECS::TaskDefinition"))
    .map((r) => r.Properties.ContainerDefinitions[0])
    .find((c) => c.Name === "api");
  const hops = (api.Environment as { Name: string; Value: string }[])
    .find((e) => e.Name === "LISTENER_PROXY_HOPS")?.Value;
  const want = scheme === "internal" ? "2" : "1";
  if (hops !== want) throw new Error(`a ${scheme} load balancer with LISTENER_PROXY_HOPS=${hops}; expected ${want}`);
});

if (failures.length) {
  console.log(`\n${failures.length} failed:\n  ${failures.join("\n  ")}`);
  process.exit(1);
}
console.log("\nall checks passed");

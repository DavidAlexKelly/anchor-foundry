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
 *      write, which depends on whether the load balancer is public (§850);
 *   6. a deleted file outlives the database backups that may name it (§852);
 *   7. the edge caches the web app's build output and nothing else (§865);
 *   8. invitations go through SES when the stack is given an address (§866);
 *   9. the platform can issue OpenID Connect tokens (§871).
 *
 * Run: `npx ts-node src/checks/stack-check.ts`
 */
import * as fs from "fs";
import * as path from "path";

import { App, DockerImage } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";

import { CustomerStack, OIDC_SIGNING_KEY_SECRET, STATIC_ASSETS } from "../stacks/customer-stack";

(DockerImage as unknown as { fromBuild: () => DockerImage }).fromBuild =
  () => DockerImage.fromRegistry("bundling-skipped");

const context = JSON.parse(
  fs.readFileSync(path.join(__dirname, "..", "..", "cdk.json"), "utf8")
).context;

function synth(platformUrl?: string, inviteFromEmail?: string): Template {
  const app = new App({ context: { ...context, "aws:cdk:bundling-stacks": [] } });
  const stack = new CustomerStack(app, "PlatformStack", {
    orgSlug: "check",
    platformUrl,
    inviteFromEmail,
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
  if (!auth.includes("`${window.location.origin}/callback`")) {
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

check("the API can tell the sign-in page this pool's hosted UI (§851)", () => {
  const api = Object.values(plain.findResources("AWS::ECS::TaskDefinition"))
    .map((r) => r.Properties.ContainerDefinitions[0])
    .find((c) => c.Name === "api");
  const env = Object.fromEntries((api.Environment as { Name: string; Value: unknown }[])
    .map((e) => [e.Name, JSON.stringify(e.Value)]));
  const domain = Object.keys(plain.findResources("AWS::Cognito::UserPoolDomain"))[0];
  if (!env.COGNITO_DOMAIN?.includes(`{"Ref":"${domain}"}`)) {
    throw new Error(`COGNITO_DOMAIN is ${env.COGNITO_DOMAIN}`);
  }
  const appClient = Object.keys(plain.findResources("AWS::Cognito::UserPoolClient"))[0];
  if (env.COGNITO_CLIENT_ID !== `{"Ref":"${appClient}"}`) throw new Error(`COGNITO_CLIENT_ID is ${env.COGNITO_CLIENT_ID}`);
});

check("the control plane can read the address, scheme and all", () => {
  const outputs = plain.toJSON().Outputs ?? {};
  if (JSON.stringify(outputs.PlatformUrl?.Value) !== servedAt(plain, "")) {
    throw new Error(`PlatformUrl is ${JSON.stringify(outputs.PlatformUrl?.Value)}`);
  }
});

console.log("how long a deleted file can be recovered (§852):");

check("the data bucket keeps a previous version past the database's oldest backup", () => {
  const db = only(plain, "AWS::RDS::DBInstance").Properties;
  const buckets = Object.values(plain.findResources("AWS::S3::Bucket"))
    .filter((b) => b.Properties.VersioningConfiguration?.Status === "Enabled");
  if (buckets.length !== 1) throw new Error(`expected one versioned bucket, found ${buckets.length}`);
  const rules: Record<string, any>[] = buckets[0].Properties.LifecycleConfiguration?.Rules ?? [];
  const kept = rules.map((r) => r.NoncurrentVersionExpiration?.NoncurrentDays).filter((d) => d !== undefined);
  if (kept.length !== 1) throw new Error(`previous versions expire under ${kept.length} rules`);
  if (kept[0] < db.BackupRetentionPeriod + 7) {
    throw new Error(`previous versions last ${kept[0]} days; backups ${db.BackupRetentionPeriod}`);
  }
  if (!rules.some((r) => r.AbortIncompleteMultipartUpload?.DaysAfterInitiation)) {
    throw new Error("abandoned uploads are never cleared");
  }
  if (rules.some((r) => r.ExpirationInDays || r.ExpirationDate)) {
    throw new Error("a rule expires current objects: that is deleting customer data");
  }
});

console.log("what the edge caches (§865):");

check("the web app's build output is cached, and nothing else is", () => {
  const config = only(plain, "AWS::CloudFront::Distribution").Properties.DistributionConfig;
  // CloudFront's managed policies, by their fixed ids.
  const CACHING_OPTIMIZED = "658327ea-f89d-4fab-a63d-7e88639e58f6";
  const CACHING_DISABLED = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad";
  if (config.DefaultCacheBehavior.CachePolicyId !== CACHING_DISABLED) {
    throw new Error("pages and the API are cached at the edge");
  }
  const behaviors: Record<string, any>[] = config.CacheBehaviors ?? [];
  if (behaviors.length !== 1 || behaviors[0].PathPattern !== STATIC_ASSETS) {
    throw new Error(`cached paths: ${JSON.stringify(behaviors.map((b) => b.PathPattern))}`);
  }
  const [assets] = behaviors;
  if (assets.CachePolicyId !== CACHING_OPTIMIZED) throw new Error("the build output is not cached");
  if (assets.OriginRequestPolicyId) throw new Error("the cached path forwards viewer headers or cookies");
  if (JSON.stringify(assets.AllowedMethods) !== JSON.stringify(["GET", "HEAD"])) {
    throw new Error(`the cached path accepts ${JSON.stringify(assets.AllowedMethods)}`);
  }
  // And it is where Next actually serves its build output.
  const nextServe = fs.readFileSync(
    path.join(__dirname, "..", "..", "..", "..", "apps", "web", "Dockerfile"), "utf8");
  if (!nextServe.includes(".next/static ./apps/web/.next/static")) {
    throw new Error("the web image no longer serves .next/static: re-derive this path");
  }
});

console.log("the platform as an OpenID Connect provider (§871):");

check("the API and the worker are told the issuer and where the key is kept", () => {
  for (const name of ["api", "worker"]) {
    const container = Object.values(plain.findResources("AWS::ECS::TaskDefinition"))
      .map((r) => r.Properties.ContainerDefinitions[0])
      .find((c) => c.Name === name);
    const env = Object.fromEntries((container.Environment as { Name: string; Value: unknown }[])
      .map((e) => [e.Name, JSON.stringify(e.Value)]));
    if (env.OIDC_ISSUER !== servedAt(plain, "/api/oidc")) throw new Error(`${name}: OIDC_ISSUER is ${env.OIDC_ISSUER}`);
    if (env.OIDC_SIGNING_KEY_SECRET !== JSON.stringify(OIDC_SIGNING_KEY_SECRET)) {
      throw new Error(`${name}: OIDC_SIGNING_KEY_SECRET is ${env.OIDC_SIGNING_KEY_SECRET}`);
    }
  }
  // Inside what both roles may read, and the API create (§846).
  if (!OIDC_SIGNING_KEY_SECRET.startsWith("anchor/connections/")) {
    throw new Error("the key's secret is outside the prefix the task roles may touch");
  }
});

console.log("where invitations come from (§866):");

check("Cognito sends them unless an SES address is given, and then SES does", () => {
  const pool = (t: Template) => only(t, "AWS::Cognito::UserPool").Properties.EmailConfiguration;
  const own = pool(plain);
  if (own && own.EmailSendingAccount !== "COGNITO_DEFAULT") throw new Error(JSON.stringify(own));
  const ses = pool(synth(undefined, "platform@data.example.com"));
  if (ses?.EmailSendingAccount !== "DEVELOPER" || !JSON.stringify(ses).includes("platform@data.example.com")) {
    throw new Error(`with an address: ${JSON.stringify(ses)}`);
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

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

import { ORIGIN_READ_TIMEOUT_S } from "../constructs/services";
import { CustomerStack, HSTS_DAYS, OIDC_SIGNING_KEY_SECRET, STATIC_ASSETS } from "../stacks/customer-stack";

(DockerImage as unknown as { fromBuild: () => DockerImage }).fromBuild =
  () => DockerImage.fromRegistry("bundling-skipped");

const context = JSON.parse(
  fs.readFileSync(path.join(__dirname, "..", "..", "cdk.json"), "utf8")
).context;

function synth(
  platformUrl?: string, inviteFromEmail?: string, bootstrapTokenHash?: string,
  originAccess?: "public" | "vpc",
): Template {
  const app = new App({ context: { ...context, "aws:cdk:bundling-stacks": [] } });
  const stack = new CustomerStack(app, "PlatformStack", {
    orgSlug: "check",
    platformUrl,
    inviteFromEmail,
    bootstrapTokenHash,
    originAccess,
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

const viaVpc = synth(undefined, undefined, undefined, "vpc");

function hopsMatchScheme(template: Template): void {
  // Public, a request can reach the load balancer directly and write every
  // X-Forwarded-For entry left of the load balancer's own: only one hop can
  // be trusted. Internal behind a CloudFront VPC origin (decision 0025), the
  // entry CloudFront writes is the sender's, two from the right.
  const scheme = only(template, "AWS::ElasticLoadBalancingV2::LoadBalancer").Properties.Scheme;
  const hops = envOf(template, "api").LISTENER_PROXY_HOPS;
  const want = scheme === "internal" ? "2" : "1";
  if (hops !== want) throw new Error(`a ${scheme} load balancer with LISTENER_PROXY_HOPS=${hops}; expected ${want}`);
}

check("the proxy hops match how the load balancer is reached", () => hopsMatchScheme(plain));
check("and on a stack whose load balancer is internal (§909)", () => hopsMatchScheme(viaVpc));

console.log("how CloudFront reaches the services (decision 0025, §909):");

/** The ingress rules of the security group the load balancer's listener uses. */
function albIngress(template: Template): Record<string, any>[] {
  const alb = only(template, "AWS::ElasticLoadBalancingV2::LoadBalancer");
  const groups: string[] = alb.Properties.SecurityGroups.map(
    (g: { "Fn::GetAtt": [string, string] }) => g["Fn::GetAtt"][0]);
  const inline = groups.flatMap((id) =>
    template.findResources("AWS::EC2::SecurityGroup")[id]?.Properties.SecurityGroupIngress ?? []);
  const separate = Object.values(template.findResources("AWS::EC2::SecurityGroupIngress"))
    .map((r) => r.Properties)
    .filter((p) => groups.includes(p.GroupId?.["Fn::GetAtt"]?.[0]));
  return [...inline, ...separate];
}

function origin(template: Template): Record<string, any> {
  const config = only(template, "AWS::CloudFront::Distribution").Properties.DistributionConfig;
  if (config.Origins.length !== 1) throw new Error(`${config.Origins.length} origins`);
  return config.Origins[0];
}

check("by default, nothing changes for a stack already deployed", () => {
  const scheme = only(plain, "AWS::ElasticLoadBalancingV2::LoadBalancer").Properties.Scheme;
  if (scheme !== "internet-facing") throw new Error(`the load balancer is ${scheme}`);
  if (!albIngress(plain).some((r) => r.CidrIp === "0.0.0.0/0")) throw new Error("not open as before");
  if (!origin(plain).CustomOriginConfig || origin(plain).VpcOriginConfig) {
    throw new Error("the origin is not the load balancer's public name");
  }
  if (Object.keys(plain.findResources("AWS::CloudFront::VpcOrigin")).length) {
    throw new Error("a VPC origin was created");
  }
});

check("with originAccess=vpc, the load balancer is internal", () => {
  const alb = only(viaVpc, "AWS::ElasticLoadBalancingV2::LoadBalancer");
  if (alb.Properties.Scheme !== "internal") throw new Error(`the load balancer is ${alb.Properties.Scheme}`);
});

check("and admits the VPC, not the internet", () => {
  const rules = albIngress(viaVpc);
  if (rules.some((r) => r.CidrIp === "0.0.0.0/0" || r.CidrIpv6 === "::/0")) {
    throw new Error("still open to the internet");
  }
  const fromVpc = rules.filter((r) => r.FromPort === 80 && r.ToPort === 80
    && JSON.stringify(r.CidrIp ?? "").includes("CidrBlock"));
  if (fromVpc.length !== 1) throw new Error(`${fromVpc.length} rules admit the VPC on port 80`);
});

check("and CloudFront reaches it through a VPC origin", () => {
  const vpcOrigins = Object.entries(viaVpc.findResources("AWS::CloudFront::VpcOrigin"));
  if (vpcOrigins.length !== 1) throw new Error(`${vpcOrigins.length} VPC origins`);
  const [id, resource] = vpcOrigins[0];
  const endpoint = resource.Properties.VpcOriginEndpointConfig;
  if (endpoint.OriginProtocolPolicy !== "http-only" || endpoint.HTTPPort !== 80) {
    throw new Error(`the VPC origin is ${JSON.stringify(endpoint)}`);
  }
  if (JSON.stringify(endpoint.Arn) !== JSON.stringify(
    { Ref: Object.keys(viaVpc.findResources("AWS::ElasticLoadBalancingV2::LoadBalancer"))[0] })) {
    throw new Error("the VPC origin is not the load balancer");
  }
  const used = origin(viaVpc).VpcOriginConfig?.VpcOriginId;
  if (JSON.stringify(used) !== JSON.stringify({ "Fn::GetAtt": [id, "Id"] })) {
    throw new Error(`the distribution's origin is ${JSON.stringify(origin(viaVpc))}`);
  }
});

console.log("how long each hop waits (§918):");

function readTimeoutOf(template: Template): number | undefined {
  const o = origin(template);
  return (o.CustomOriginConfig ?? o.VpcOriginConfig)?.OriginReadTimeout;
}

function idleTimeoutOf(template: Template): number {
  const attrs: { Key: string; Value: string }[] =
    only(template, "AWS::ElasticLoadBalancingV2::LoadBalancer").Properties.LoadBalancerAttributes ?? [];
  return Number(attrs.find((a) => a.Key === "idle_timeout.timeout_seconds")?.Value ?? 60);
}

for (const [name, template] of [["public", plain], ["vpc", viaVpc]] as const) {
  check(`each hop outlasts the one in front of it (${name} origin)`, () => {
    // CloudFront gives up before the load balancer drops a quiet connection,
    // and the load balancer drops it before a server does - so neither ever
    // sends a request down a connection the next hop has already closed.
    const read = readTimeoutOf(template);
    const idle = idleTimeoutOf(template);
    const api = Number(envOf(template, "api").UVICORN_TIMEOUT_KEEP_ALIVE);
    const web = Number(envOf(template, "web").KEEP_ALIVE_TIMEOUT) / 1000;
    if (read !== ORIGIN_READ_TIMEOUT_S) throw new Error(`CloudFront waits ${read} s`);
    if (!(read < idle)) throw new Error(`CloudFront ${read} s, load balancer ${idle} s`);
    for (const [server, keep] of [["api", api], ["web", web]] as const) {
      if (!(idle < keep)) throw new Error(`load balancer ${idle} s, ${server} keeps ${keep} s`);
    }
  });
}

console.log("HTTPS from the first request on (§920):");

check("every behaviour tells the browser to keep to HTTPS for a year", () => {
  const config = only(plain, "AWS::CloudFront::Distribution").Properties.DistributionConfig;
  const behaviours = [config.DefaultCacheBehavior, ...(config.CacheBehaviors ?? [])];
  const policies = plain.findResources("AWS::CloudFront::ResponseHeadersPolicy");
  for (const behaviour of behaviours) {
    const ref = behaviour.ResponseHeadersPolicyId?.Ref;
    const policy = ref && policies[ref]?.Properties.ResponseHeadersPolicyConfig;
    const hsts = policy?.SecurityHeadersConfig?.StrictTransportSecurity;
    if (!hsts) throw new Error(`${behaviour.PathPattern ?? "the default behaviour"} sends no HSTS`);
    if (hsts.AccessControlMaxAgeSec < HSTS_DAYS * 86400 || !hsts.Override) {
      throw new Error(`HSTS is ${JSON.stringify(hsts)}`);
    }
  }
});

console.log("who creates the first owner (§886):");

function envOf(template: Template, service: string): Record<string, string> {
  const found = Object.entries(template.findResources("AWS::ECS::TaskDefinition"))
    .filter(([id]) => id.startsWith(`Services${service}TaskDef`));
  if (found.length !== 1) throw new Error(`expected one ${service} task definition`);
  const env: { Name: string; Value: string }[] = found[0][1].Properties.ContainerDefinitions[0].Environment ?? [];
  return Object.fromEntries(env.map((e) => [e.Name, e.Value]));
}

const HASH = "a".repeat(64);
const provisioned = synth(undefined, undefined, HASH);

check("the API refuses all but the provisioner's token when given its hash", () => {
  const api = envOf(provisioned, "api");
  if (api.BOOTSTRAP_TOKEN_SHA256 !== HASH) throw new Error(`BOOTSTRAP_TOKEN_SHA256 is ${api.BOOTSTRAP_TOKEN_SHA256}`);
  if ("BOOTSTRAP_TOKEN_SHA256" in envOf(provisioned, "worker")) throw new Error("the worker was given it");
});

check("without it, the setup page works as before", () => {
  if ("BOOTSTRAP_TOKEN_SHA256" in envOf(plain, "api")) throw new Error("set with no hash given");
});

if (failures.length) {
  console.log(`\n${failures.length} failed:\n  ${failures.join("\n  ")}`);
  process.exit(1);
}
console.log("\nall checks passed");

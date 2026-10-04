#!/usr/bin/env node
import { App } from "aws-cdk-lib";
import { CustomerStack } from "./stacks/customer-stack";

/**
 * CDK entry point. The control plane invokes `cdk deploy` with per-customer
 * context (spec §6): org slug, platform URL, vendor ECR registry, image tag,
 * and the customer's chosen region.
 */
const app = new App();

const orgSlug = app.node.tryGetContext("orgSlug") as string | undefined;
const platformUrl = app.node.tryGetContext("platformUrl") as string | undefined;
const vendorEcrRegistry = app.node.tryGetContext("vendorEcrRegistry") as string | undefined;
const imageTag = (app.node.tryGetContext("imageTag") as string | undefined) ?? "latest";
const region = app.node.tryGetContext("region") as string | undefined;
// Defaults true (spec §10 security default) - the control plane's own
// deploys never pass this context key, so every real customer stack keeps
// the safe default. Only ever set to "false" for a throwaway dry-run stack
// that expects to be torn down repeatedly: without it, any failed CREATE
// that reaches the RDS instance forces a manual teardown before
// CloudFormation's own rollback can finish (see STATUS.md).
const deletionProtectionCtx = app.node.tryGetContext("deletionProtection") as string | undefined;
const deletionProtection = deletionProtectionCtx !== "false";

// Where objects live (§814). Postgres unless a stack says otherwise, and a
// stack says otherwise only after its objects have been copied across
// (docs/deploying.md, "Moving objects to OpenSearch"): switching first would
// point the API at an empty index.
const objectStore = (app.node.tryGetContext("objectStore") as string | undefined) ?? "postgres";
if (objectStore !== "postgres" && objectStore !== "opensearch") {
  throw new Error(`Invalid objectStore: ${objectStore} (postgres or opensearch)`);
}

// Where the stack's alarms are sent (§815). Optional: the topic exists either
// way, and its ARN is a stack output for anything else to subscribe.
const alarmEmail = app.node.tryGetContext("alarmEmail") as string | undefined;
if (alarmEmail !== undefined && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(alarmEmail)) {
  throw new Error(`Invalid alarmEmail: ${alarmEmail}`);
}

if (!orgSlug || !vendorEcrRegistry) {
  throw new Error(
    "Missing required context: orgSlug, vendorEcrRegistry (passed by the control plane)"
  );
}
// Optional since §849: a custom address, beside the distribution's own, which
// the stack always allows. Sign-in sends a viewer back to `<address>/callback`,
// so anything but a bare https origin would be an address nobody is sent to.
if (platformUrl !== undefined && !/^https:\/\/[a-z0-9.-]+(:\d+)?$/i.test(platformUrl)) {
  throw new Error(`Invalid platformUrl: ${platformUrl} (an https origin, e.g. https://data.example.com)`);
}
if (!/^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/.test(orgSlug)) {
  throw new Error(`Invalid orgSlug: ${orgSlug}`);
}

new CustomerStack(app, "PlatformStack", {
  orgSlug,
  platformUrl,
  vendorEcrRegistry,
  imageTag,
  deletionProtection,
  objectStore,
  alarmEmail,
  env: region ? { region } : undefined,
  description: `Platform stack for ${orgSlug} - provisioned by the platform control plane`,
});

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

if (!orgSlug || !platformUrl || !vendorEcrRegistry) {
  throw new Error(
    "Missing required context: orgSlug, platformUrl, vendorEcrRegistry (passed by the control plane)"
  );
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
  env: region ? { region } : undefined,
  description: `Platform stack for ${orgSlug} - provisioned by the platform control plane`,
});

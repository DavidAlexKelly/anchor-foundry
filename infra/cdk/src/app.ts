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
  env: region ? { region } : undefined,
  description: `Platform stack for ${orgSlug} — provisioned by the platform control plane`,
});

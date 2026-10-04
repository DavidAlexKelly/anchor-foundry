/**
 * Assertions about what the load balancer's web ACL refuses (§847).
 *
 * The Common Rule Set blocked every request body over 8 KB, so a deployed
 * stack refused every upload, attachment, listener push and large save before
 * the API saw it. Six of its rules now count instead (constructs/waf.ts says
 * why each). What is checked is what a later edit could get wrong without any
 * diff showing it:
 *
 *   1. each counted rule is one the set actually has - a misspelt name
 *      overrides nothing, and the rule goes on blocking;
 *   2. only those six: every other rule in both sets still blocks, and
 *      neither set is counted as a whole;
 *   3. the API bounds a body itself, since the WAF no longer does;
 *   4. the customer stack uses these rules, not a copy of its own.
 *
 * Run: `npx ts-node src/checks/waf-check.ts`
 */
import * as fs from "fs";
import * as path from "path";

import { App, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import * as wafv2 from "aws-cdk-lib/aws-wafv2";

import { COUNTED_COMMON_RULES, webAclRules } from "../constructs/waf";

// The rules of AWSManagedRulesCommonRuleSet, from AWS's managed rule groups
// list. Written out because the check cannot ask AWS.
const COMMON_RULE_SET = new Set([
  "NoUserAgent_HEADER", "UserAgent_BadBots_HEADER",
  "SizeRestrictions_QUERYSTRING", "SizeRestrictions_Cookie_HEADER",
  "SizeRestrictions_BODY", "SizeRestrictions_URIPATH",
  "EC2MetaDataSSRF_BODY", "EC2MetaDataSSRF_COOKIE", "EC2MetaDataSSRF_URIPATH",
  "EC2MetaDataSSRF_QUERYARGUMENTS",
  "GenericLFI_QUERYARGUMENTS", "GenericLFI_URIPATH", "GenericLFI_BODY",
  "RestrictedExtensions_URIPATH", "RestrictedExtensions_QUERYARGUMENTS",
  "GenericRFI_QUERYARGUMENTS", "GenericRFI_BODY", "GenericRFI_URIPATH",
  "CrossSiteScripting_COOKIE", "CrossSiteScripting_QUERYARGUMENTS",
  "CrossSiteScripting_BODY", "CrossSiteScripting_URIPATH",
]);

const repo = path.join(__dirname, "..", "..", "..", "..");
const app = new App();
const stack = new Stack(app, "CheckStack", { env: { account: "111111111111", region: "eu-west-2" } });
new wafv2.CfnWebACL(stack, "Waf", {
  scope: "REGIONAL",
  defaultAction: { allow: {} },
  visibilityConfig: { cloudWatchMetricsEnabled: true, metricName: "check", sampledRequestsEnabled: true },
  rules: webAclRules(),
});
const acls = Object.values(Template.fromStack(stack).findResources("AWS::WAFv2::WebACL"));
const rules: Record<string, any>[] = acls[0].Properties.Rules;

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

function group(name: string): Record<string, any> {
  const found = rules.filter((r) => r.Statement?.ManagedRuleGroupStatement?.Name === name);
  if (found.length !== 1) throw new Error(`expected one ${name} rule, found ${found.length}`);
  return found[0];
}

console.log("web ACL (§847):");

check("every counted rule is one the Common Rule Set has", () => {
  const unknown = COUNTED_COMMON_RULES.filter((name) => !COMMON_RULE_SET.has(name));
  if (unknown.length) throw new Error(`not in the set: ${unknown.join(", ")}`);
});

check("the Common Rule Set counts those six and blocks on the rest", () => {
  const common = group("AWSManagedRulesCommonRuleSet");
  if (JSON.stringify(common.OverrideAction) !== JSON.stringify({ None: {} })) {
    throw new Error(`the whole set is overridden: ${JSON.stringify(common.OverrideAction)}`);
  }
  const overrides: Record<string, any>[] = common.Statement.ManagedRuleGroupStatement.RuleActionOverrides ?? [];
  const counted = overrides.filter((o) => JSON.stringify(o.ActionToUse) === JSON.stringify({ Count: {} }));
  if (counted.length !== overrides.length) throw new Error("an override does something other than count");
  const names = counted.map((o) => o.Name).sort();
  const expected = [...COUNTED_COMMON_RULES].sort();
  if (JSON.stringify(names) !== JSON.stringify(expected)) {
    throw new Error(`counted ${names.join(", ")}; expected ${expected.join(", ")}`);
  }
  // The ones that stay are the point of having the set at all.
  for (const kept of ["EC2MetaDataSSRF_BODY", "CrossSiteScripting_QUERYARGUMENTS", "GenericLFI_URIPATH"]) {
    if (names.includes(kept)) throw new Error(`${kept} no longer blocks`);
  }
});

check("the known-bad-inputs set blocks on every rule", () => {
  const bad = group("AWSManagedRulesKnownBadInputsRuleSet");
  if (JSON.stringify(bad.OverrideAction) !== JSON.stringify({ None: {} })) throw new Error("the set is overridden");
  if (bad.Statement.ManagedRuleGroupStatement.RuleActionOverrides) throw new Error("a rule in it is overridden");
});

check("the API bounds a body itself, now that the WAF does not", () => {
  const source = fs.readFileSync(path.join(repo, "apps", "api", "src", "lib", "body_limit.py"), "utf8");
  const limit = source.match(/^BODY_MAX_BYTES = (\d+) \* MIB$/m);
  const upload = source.match(/^UPLOAD_MAX_BYTES = (\d+) \* MIB$/m);
  if (!limit || !upload) throw new Error("body_limit.py no longer states BODY_MAX_BYTES and UPLOAD_MAX_BYTES in MiB");
  if (Number(limit[1]) > 64 || Number(upload[1]) > 256) {
    throw new Error(`the API's own limits are ${limit[1]} and ${upload[1]} MiB`);
  }
});

check("the customer stack uses these rules", () => {
  const source = fs.readFileSync(path.join(__dirname, "..", "stacks", "customer-stack.ts"), "utf8");
  if (!/rules: webAclRules\(\),/.test(source)) throw new Error("customer-stack.ts builds its web ACL some other way");
  if (/managedRuleGroupStatement/.test(source)) throw new Error("customer-stack.ts names a managed rule group itself");
});

if (failures.length) {
  console.log(`\n${failures.length} failed:\n  ${failures.join("\n  ")}`);
  process.exit(1);
}
console.log("\nall checks passed");

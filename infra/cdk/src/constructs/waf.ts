import * as wafv2 from "aws-cdk-lib/aws-wafv2";

/**
 * The rules of the load balancer's web ACL (§10, §847).
 *
 * AWS's Common Rule Set is written for a website, and this is a data platform:
 * what its requests carry is the customer's own data. Five of its rules refuse
 * that data on sight, so they count instead of blocking - matches still show
 * in the WAF's metrics and sampled requests, and nothing is refused for them.
 *
 *   - `SizeRestrictions_BODY` blocks every body over 8 KB. Every dataset
 *     upload, attachment and listener push past that size, and every large
 *     save (a Workshop module, a pipeline, a code file), would get the WAF's
 *     403 before reaching the API. The API bounds bodies itself, at 16 MB and
 *     51 MB for uploads (`apps/api/src/lib/body_limit.py`, §832).
 *   - `SizeRestrictions_QUERYSTRING` blocks query strings over 2 KB. A screen
 *     reading back the types it has chosen (`?ids=`) or the related artifacts
 *     of the pipeline nodes it has selected (`?node=`) passes that at about
 *     fifty.
 *   - `GenericRFI_BODY`, `GenericLFI_BODY` and `CrossSiteScripting_BODY` match
 *     URLs with IP addresses, `../` paths and markup in a body. A connection
 *     to `http://10.0.4.12/`, a code file that opens `../data.csv`, and a
 *     Markdown widget are each what they are looking for. Queries reach
 *     Postgres as parameters, and the web app renders text through React's
 *     escaping, which is where those attacks would otherwise land.
 *   - `NoUserAgent_HEADER` blocks requests without a `User-Agent`. A
 *     listener's endpoint (`/api/listen/{token}`) exists for other systems to
 *     push to, and plenty of them send none.
 *
 * Every other rule in both sets still blocks.
 */
export const COUNTED_COMMON_RULES = [
  "SizeRestrictions_BODY",
  "SizeRestrictions_QUERYSTRING",
  "GenericRFI_BODY",
  "GenericLFI_BODY",
  "CrossSiteScripting_BODY",
  "NoUserAgent_HEADER",
] as const;

function visibility(metricName: string): wafv2.CfnWebACL.VisibilityConfigProperty {
  return { cloudWatchMetricsEnabled: true, metricName, sampledRequestsEnabled: true };
}

export function webAclRules(): wafv2.CfnWebACL.RuleProperty[] {
  return [
    {
      name: "AWSManagedCommonRules",
      priority: 0,
      overrideAction: { none: {} },
      statement: {
        managedRuleGroupStatement: {
          vendorName: "AWS",
          name: "AWSManagedRulesCommonRuleSet",
          ruleActionOverrides: COUNTED_COMMON_RULES.map((name) => ({
            name,
            actionToUse: { count: {} },
          })),
        },
      },
      visibilityConfig: visibility("common-rules"),
    },
    {
      name: "AWSManagedKnownBadInputs",
      priority: 1,
      overrideAction: { none: {} },
      statement: {
        managedRuleGroupStatement: {
          vendorName: "AWS",
          name: "AWSManagedRulesKnownBadInputsRuleSet",
        },
      },
      visibilityConfig: visibility("bad-inputs"),
    },
  ];
}

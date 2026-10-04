/**
 * Assertions about the stack's alarms (§815; roadmap phase 3, E.3).
 *
 * An alarm that cannot fire looks exactly like one that has not needed to, so
 * what is checked is what decides whether these can: each filter reads the
 * API's own log lines, each alarm reaches the topic both ways, a quiet API is
 * not an incident, and the email goes where the stack was told. Whether the
 * filter patterns name fields the API really writes is checked from the other
 * side, in `apps/api/tests/test_observability.py`.
 *
 * Run: `npx ts-node src/checks/monitoring-check.ts`
 */
import * as fs from "fs";
import * as path from "path";

import { App, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as cognito from "aws-cdk-lib/aws-cognito";

import { DataStoresConstruct } from "../constructs/data-stores";
import { METRIC_NAMESPACE, MonitoringConstruct } from "../constructs/monitoring";
import { ServicesConstruct } from "../constructs/services";

const context = JSON.parse(
  fs.readFileSync(path.join(__dirname, "..", "..", "cdk.json"), "utf8")
).context;

function build(alarmEmail?: string): Template {
  const app = new App({ context });
  const stack = new Stack(app, "CheckStack", { env: { account: "111111111111", region: "eu-west-2" } });
  const vpc = new ec2.Vpc(stack, "Vpc", { maxAzs: 2, natGateways: 1 });
  const endpointSg = new ec2.SecurityGroup(stack, "EndpointSg", { vpc, allowAllOutbound: false });
  const data = new DataStoresConstruct(stack, "Data", { vpc, orgSlug: "check" });
  const services = new ServicesConstruct(stack, "Services", {
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
  });
  new MonitoringConstruct(stack, "Monitoring", {
    logGroup: services.logGroup,
    cluster: services.cluster,
    apiService: services.apiService,
    workerService: services.workerService,
    apiTargetGroup: services.apiTargetGroup,
    database: data.database,
    alarmEmail,
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

const quiet = build();
const told = build("ops@example.com");
const alarms = Object.entries(quiet.findResources("AWS::CloudWatch::Alarm"));
const topicId = Object.keys(quiet.findResources("AWS::SNS::Topic"))[0];

function alarm(prefix: string): Record<string, unknown> {
  const found = alarms.filter(([id]) => id.startsWith(`Monitoring${prefix}`));
  if (found.length !== 1) throw new Error(`expected one ${prefix} alarm, found ${found.length}`);
  return found[0][1].Properties ?? {};
}

console.log("monitoring (§815):");

check("the API's lines are counted by the patterns its formatter matches", () => {
  const filters = Object.values(quiet.findResources("AWS::Logs::MetricFilter")).map((f) => ({
    pattern: f.Properties?.FilterPattern,
    name: f.Properties?.MetricTransformations?.[0]?.MetricName,
    value: f.Properties?.MetricTransformations?.[0]?.MetricValue,
    namespace: f.Properties?.MetricTransformations?.[0]?.MetricNamespace,
    group: JSON.stringify(f.Properties?.LogGroupName),
  }));
  const expected: Record<string, [string, string]> = {
    ApiRequests: ['{ $.logger = "anchor.access" }', "1"],
    ApiServerErrors: ['{ $.logger = "anchor.access" && $.status >= 500 }', "1"],
    ApiUnhandledErrors: ['{ $.logger = "anchor.error" }', "1"],
    ApiLatency: ['{ $.logger = "anchor.access" }', "$.duration_ms"],
  };
  if (filters.length !== Object.keys(expected).length) {
    throw new Error(`expected ${Object.keys(expected).length} filters, found ${filters.length}`);
  }
  for (const filter of filters) {
    const want = expected[filter.name];
    if (!want) throw new Error(`unexpected filter ${filter.name}`);
    if (filter.pattern !== want[0] || filter.value !== want[1]) {
      throw new Error(`${filter.name}: ${filter.pattern} -> ${filter.value}`);
    }
    if (filter.namespace !== METRIC_NAMESPACE) throw new Error(`${filter.name} in ${filter.namespace}`);
    if (!filter.group.includes("ServicesLogs")) throw new Error(`${filter.name} reads ${filter.group}`);
  }
});

check("every alarm reaches the topic when it fires and when it clears", () => {
  if (alarms.length !== 8) throw new Error(`expected 8 alarms, found ${alarms.length}`);
  for (const [id, made] of alarms) {
    for (const key of ["AlarmActions", "OKActions"]) {
      if (!JSON.stringify(made.Properties?.[key] ?? []).includes(topicId)) {
        throw new Error(`${id} has no ${key} to the topic`);
      }
    }
  }
});

check("a quiet API is not an incident", () => {
  for (const [id, made] of alarms) {
    if (made.Properties?.TreatMissingData !== "notBreaching") {
      throw new Error(`${id} treats missing data as ${made.Properties?.TreatMissingData}`);
    }
  }
});

check("the error alarm is a rate, and needs traffic to be one", () => {
  const props = alarm("ApiErrorRate");
  const rendered = JSON.stringify(props.Metrics);
  if (!rendered.includes("IF(requests >= 20, 100 * errors / requests, 0)")) {
    throw new Error(`expression: ${rendered.slice(0, 200)}`);
  }
  for (const name of ["ApiRequests", "ApiServerErrors"]) {
    if (!rendered.includes(name)) throw new Error(`the rate does not read ${name}`);
  }
  if (props.Threshold !== 5 || props.ComparisonOperator !== "GreaterThanThreshold") {
    throw new Error(`${props.ComparisonOperator} ${props.Threshold}`);
  }
});

check("one unhandled error is enough", () => {
  const props = alarm("ApiUnhandledError");
  if (props.Threshold !== 1 || props.ComparisonOperator !== "GreaterThanOrEqualToThreshold"
      || props.EvaluationPeriods !== 1 || props.MetricName !== "ApiUnhandledErrors"
      || props.Statistic !== "Sum") {
    throw new Error(JSON.stringify(props).slice(0, 200));
  }
});

check("latency is judged at p95, in milliseconds", () => {
  const props = alarm("ApiLatency");
  if (props.ExtendedStatistic !== "p95" || props.Threshold !== 2000 || props.MetricName !== "ApiLatency") {
    throw new Error(`${props.ExtendedStatistic} ${props.Threshold} ${props.MetricName}`);
  }
});

check("the API and the worker are each watched for having no task", () => {
  for (const [prefix, service] of [["ApiNotRunning", "ServicesapiService"],
                                   ["WorkerNotRunning", "ServicesworkerService"]]) {
    const props = alarm(prefix);
    const dims = JSON.stringify(props.Dimensions);
    if (props.MetricName !== "RunningTaskCount" || props.Statistic !== "Minimum" || !dims.includes(service)
        || props.Threshold !== 1 || props.ComparisonOperator !== "LessThanThreshold") {
      throw new Error(`${prefix}: ${props.MetricName} ${props.Statistic} ${dims}`);
    }
  }
});

check("the database is watched for storage and CPU", () => {
  const storage = alarm("DatabaseStorage");
  if (storage.MetricName !== "FreeStorageSpace" || storage.ComparisonOperator !== "LessThanThreshold") {
    throw new Error(`storage: ${storage.MetricName} ${storage.ComparisonOperator}`);
  }
  if (alarm("DatabaseCpu").MetricName !== "CPUUtilization") throw new Error("cpu metric");
  if (alarm("ApiUnhealthyTargets").MetricName !== "UnHealthyHostCount") throw new Error("targets metric");
});

check("the email is subscribed only when given", () => {
  const none = Object.keys(quiet.findResources("AWS::SNS::Subscription"));
  if (none.length !== 0) throw new Error(`${none.length} subscription(s) with no email`);
  const subs = Object.values(told.findResources("AWS::SNS::Subscription"));
  if (subs.length !== 1 || subs[0].Properties?.Protocol !== "email"
      || subs[0].Properties?.Endpoint !== "ops@example.com") {
    throw new Error(JSON.stringify(subs.map((s) => s.Properties)));
  }
});

if (failures.length > 0) {
  console.log(`\n${failures.length} check(s) failed:\n  ${failures.join("\n  ")}`);
  process.exit(1);
}
console.log("\nall checks passed");

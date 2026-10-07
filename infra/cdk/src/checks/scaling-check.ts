/**
 * Assertions about how many of each task run (§841).
 *
 * What is checked is what an outage or a doubled schedule would come from: the
 * API and the web server never fall to one task and scale on CPU to a ceiling,
 * the worker is exactly one and never scaled - its Dagster daemon fires every
 * schedule, so a second worker would run each one twice - and the API's
 * ceiling, at its pool's largest, fits under the database's connection limit.
 *
 * Run: `npx ts-node src/checks/scaling-check.ts`
 */
import * as fs from "fs";
import * as path from "path";

import { App, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as cognito from "aws-cdk-lib/aws-cognito";

import { DataStoresConstruct } from "../constructs/data-stores";
import {
  API_TASKS,
  API_DUCKDB_SLOTS,
  DUCKDB_MEMORY_MIB,
  DUCKDB_THREADS,
  PROCESS_ALLOWANCE_MIB,
  SCALE_AT_CPU_PERCENT,
  ServicesConstruct,
  TASK_MEMORY_MIB,
  WEB_TASKS,
  WORKER_RUN_PROCESS_MIB,
} from "../constructs/services";

const context = JSON.parse(
  fs.readFileSync(path.join(__dirname, "..", "..", "cdk.json"), "utf8")
).context;

const app = new App({ context });
const stack = new Stack(app, "CheckStack", { env: { account: "111111111111", region: "eu-west-2" } });
const vpc = new ec2.Vpc(stack, "Vpc", { maxAzs: 2, natGateways: 1 });
const endpointSg = new ec2.SecurityGroup(stack, "EndpointSg", { vpc, allowAllOutbound: false });
const data = new DataStoresConstruct(stack, "Data", { vpc, orgSlug: "check" });
new ServicesConstruct(stack, "Services", {
  vpc,
  vpcEndpointSecurityGroup: endpointSg,
  dataBucket: data.dataBucket,
  dbSecret: data.dbSecret,
  appDbSecret: data.appDbSecret,
  databaseHost: "db.example",
  databasePort: "5432",
  searchEndpoint: "search.example",
  userPool: cognito.UserPool.fromUserPoolId(stack, "Pool", "eu-west-2_check"),
  userPoolClientId: "check-client",
  apiImage: "registry/api",
  workerImage: "registry/worker",
  webImage: "registry/web",
  imageTag: "check",
});
const template = Template.fromStack(stack);

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

const services = template.findResources("AWS::ECS::Service");
const targets = template.findResources("AWS::ApplicationAutoScaling::ScalableTarget");
const policies = template.findResources("AWS::ApplicationAutoScaling::ScalingPolicy");

function serviceId(name: string): string {
  const found = Object.keys(services).filter((id) => id.startsWith(`Services${name}Service`));
  if (found.length !== 1) throw new Error(`expected one ${name} service, found ${found.length}`);
  return found[0];
}

function targetOf(name: string): Record<string, any> | undefined {
  const id = serviceId(name);
  return Object.values(targets).find((t) => JSON.stringify(t.Properties?.ResourceId).includes(id));
}

console.log("scaling (§841):");

for (const [name, bounds] of [["api", API_TASKS], ["web", WEB_TASKS]] as const) {
  check(`the ${name} starts at ${bounds.min} tasks and scales to ${bounds.max}`, () => {
    const desired = services[serviceId(name)].Properties?.DesiredCount;
    if (desired !== bounds.min) throw new Error(`desired count ${desired}`);
    const target = targetOf(name);
    if (!target) throw new Error("no scalable target");
    const { MinCapacity, MaxCapacity } = target.Properties;
    if (MinCapacity !== bounds.min || MaxCapacity !== bounds.max) {
      throw new Error(`scales ${MinCapacity}..${MaxCapacity}`);
    }
    if (bounds.min < 2) throw new Error("one task is an outage waiting for a crash");
  });
}

check("each scales on CPU", () => {
  const cpu = Object.values(policies).filter((p) =>
    p.Properties?.TargetTrackingScalingPolicyConfiguration?.PredefinedMetricSpecification
      ?.PredefinedMetricType === "ECSServiceAverageCPUUtilization");
  if (cpu.length !== 2) throw new Error(`expected 2 CPU policies, found ${cpu.length}`);
  for (const policy of cpu) {
    const value = policy.Properties.TargetTrackingScalingPolicyConfiguration.TargetValue;
    if (value !== SCALE_AT_CPU_PERCENT) throw new Error(`target ${value}`);
  }
});

check("the worker is one task and is never scaled", () => {
  const desired = services[serviceId("worker")].Properties?.DesiredCount;
  if (desired !== 1) throw new Error(`desired count ${desired}`);
  if (targetOf("worker")) throw new Error("the worker has a scalable target");
});

check("the API at its ceiling fits the database's connections", () => {
  // apps/api/src/lib/db.py: pool_size=10, max_overflow=20.
  const perTask = 10 + 20;
  // A db.t4g.medium (4 GiB) allows LEAST(memory / 9531392, 5000), about 450;
  // half of it for the API leaves the worker, migrations and operators room.
  const instance = JSON.stringify(template.findResources("AWS::RDS::DBInstance"));
  if (!instance.includes("db.t4g.medium")) throw new Error("the database is no longer a t4g.medium: re-derive this budget");
  const limit = Math.floor((4 * 1024 ** 3) / 9531392);
  if (API_TASKS.max * perTask > limit / 2) {
    throw new Error(`${API_TASKS.max} tasks x ${perTask} = ${API_TASKS.max * perTask} of ${limit}`);
  }
});

const taskDefs = template.findResources("AWS::ECS::TaskDefinition");

function taskDefOf(name: string): Record<string, any> {
  const found = Object.entries(taskDefs).filter(([id]) => id.startsWith(`Services${name}TaskDef`));
  if (found.length !== 1) throw new Error(`expected one ${name} task definition, found ${found.length}`);
  return found[0][1];
}

console.log("memory (§875):");

for (const name of ["api", "worker"] as const) {
  check(`the ${name} holds each DuckDB to its share of the task`, () => {
    const props = taskDefOf(name).Properties;
    const memory = Number(props.Memory);
    if (memory !== TASK_MEMORY_MIB[name]) throw new Error(`task memory ${memory}`);
    const env: { Name: string; Value: string }[] = props.ContainerDefinitions[0].Environment ?? [];
    const value = (key: string) => env.find((e) => e.Name === key)?.Value;
    if (value("DUCKDB_MEMORY_LIMIT") !== `${DUCKDB_MEMORY_MIB}MiB`) {
      throw new Error(`DUCKDB_MEMORY_LIMIT ${value("DUCKDB_MEMORY_LIMIT")}`);
    }
    if (value("DUCKDB_THREADS") !== String(DUCKDB_THREADS)) {
      throw new Error(`DUCKDB_THREADS ${value("DUCKDB_THREADS")}`);
    }
    // Two operations at once, each resident at up to one and a half times
    // its limit, beside the process itself.
    const needed = 2 * 1.5 * DUCKDB_MEMORY_MIB + PROCESS_ALLOWANCE_MIB;
    if (needed > memory) throw new Error(`needs ${needed} MiB of ${memory}`);
    if (name === "api") {
      // §911: and the API holds itself to that many. Without DUCKDB_SLOTS
      // nothing did, and anyio's forty worker threads were the only bound.
      if (value("DUCKDB_SLOTS") !== String(API_DUCKDB_SLOTS)) {
        throw new Error(`DUCKDB_SLOTS ${value("DUCKDB_SLOTS")}`);
      }
      const held = API_DUCKDB_SLOTS * 1.5 * DUCKDB_MEMORY_MIB + PROCESS_ALLOWANCE_MIB;
      if (held > memory) throw new Error(`${API_DUCKDB_SLOTS} slots need ${held} MiB of ${memory}`);
    }
    if (name === "worker") {
      // §894: the daemon, every run's process, and the heavy runs' DuckDB,
      // with the numbers the worker's own Dagster settings declare.
      const settings = fs.readFileSync(
        path.join(__dirname, "..", "..", "..", "..", "apps", "worker", "dagster.yaml"), "utf8");
      const runs = Number(/max_concurrent_runs:\s*(\d+)/.exec(settings)?.[1]);
      const heavy = Number(/value:\s*heavy\s*\n\s*limit:\s*(\d+)/.exec(settings)?.[1]);
      if (!runs || !heavy) throw new Error("apps/worker/dagster.yaml no longer declares its limits");
      const worst = PROCESS_ALLOWANCE_MIB + runs * WORKER_RUN_PROCESS_MIB + heavy * 1.5 * DUCKDB_MEMORY_MIB;
      if (worst > memory) throw new Error(`${runs} runs, ${heavy} heavy, need ${worst} MiB of ${memory}`);
    }
  });
}

if (failures.length) {
  console.log(`\n${failures.length} failed:\n  ${failures.join("\n  ")}`);
  process.exit(1);
}
console.log("\nall checks passed");

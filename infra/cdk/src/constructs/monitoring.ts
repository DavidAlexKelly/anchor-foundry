import { Duration } from "aws-cdk-lib";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
import * as actions from "aws-cdk-lib/aws-cloudwatch-actions";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as logs from "aws-cdk-lib/aws-logs";
import * as rds from "aws-cdk-lib/aws-rds";
import * as sns from "aws-cdk-lib/aws-sns";
import * as subscriptions from "aws-cdk-lib/aws-sns-subscriptions";
import { Construct } from "constructs";

export interface MonitoringProps {
  /** Where every service's container writes (`ServicesConstruct.logGroup`). */
  readonly logGroup: logs.ILogGroup;
  readonly cluster: ecs.ICluster;
  readonly apiService: ecs.FargateService;
  readonly workerService: ecs.FargateService;
  readonly webService: ecs.FargateService;
  readonly apiTargetGroup: elbv2.ApplicationTargetGroup;
  readonly webTargetGroup: elbv2.ApplicationTargetGroup;
  readonly database: rds.DatabaseInstance;
  /** Subscribed to every alarm when given (app.ts's `alarmEmail` context).
   * Without it the topic still exists, for whatever the operator attaches. */
  readonly alarmEmail?: string;
}

/**
 * Connections the database is held to warn at (§925): four in five of what a
 * db.t4g.medium allows, LEAST(memory / 9531392, 5000). scaling-check.ts
 * budgets the API's pools to half of it; past this, something holds far more
 * than any pool should, and the next task to start will be refused one.
 */
export const DATABASE_CONNECTIONS_ALARM = Math.floor(0.8 * Math.floor((4 * 1024 ** 3) / 9531392));

/** What the API's JSON lines are counted as (§815). */
export const METRIC_NAMESPACE = "Anchor/Platform";

/**
 * The deployed half of observability (roadmap phase 3, E.3; §815).
 *
 * §802 made the API write one JSON line per request on `anchor.access` and a
 * traceback on `anchor.error`, and the `awslogs` driver already ships both to
 * CloudWatch Logs. What nothing did was look at them. This counts them -
 * metric filters on the lines themselves, so there is no scraper to run - and
 * alarms, onto one SNS topic, on what an operator would be woken for:
 *
 *   - the API answering 5xx to more than 5% of requests;
 *   - any unhandled error, each of which already carries its request id;
 *   - p95 latency over two seconds;
 *   - the API, the worker or the web server with no task running (§925);
 *   - the worker's scheduled runs failing (§889);
 *   - pages failing in people's browsers (§926);
 *   - the API's or the web server's targets failing the load balancer's
 *     health check (§925);
 *   - the database short of storage, of CPU, or of connections (§925).
 *
 * The filters name the formatter's own fields (`logger`, `status`,
 * `duration_ms`); `apps/api/tests/test_observability.py` reads them out of
 * this file and checks each against a line the API really writes, so a
 * renamed field fails there rather than leaving an alarm that can never fire.
 */
export class MonitoringConstruct extends Construct {
  public readonly topic: sns.Topic;
  public readonly alarms: cloudwatch.Alarm[] = [];

  constructor(scope: Construct, id: string, props: MonitoringProps) {
    super(scope, id);
    this.topic = new sns.Topic(this, "Alarms", { displayName: "Platform alarms" });
    if (props.alarmEmail) {
      this.topic.addSubscription(new subscriptions.EmailSubscription(props.alarmEmail));
    }

    const counted = (name: string, pattern: string, value = "1"): cloudwatch.Metric => {
      new logs.MetricFilter(this, `${name}Filter`, {
        logGroup: props.logGroup,
        filterPattern: logs.FilterPattern.literal(pattern),
        metricNamespace: METRIC_NAMESPACE,
        metricName: name,
        metricValue: value,
      });
      return new cloudwatch.Metric({
        namespace: METRIC_NAMESPACE,
        metricName: name,
        period: Duration.minutes(5),
        statistic: "Sum",
      });
    };
    const requests = counted("ApiRequests", '{ $.logger = "anchor.access" }');
    const serverErrors = counted(
      "ApiServerErrors",
      '{ $.logger = "anchor.access" && $.status >= 500 }'
    );
    const unhandled = counted("ApiUnhandledErrors", '{ $.logger = "anchor.error" }');
    const latency = counted("ApiLatency", '{ $.logger = "anchor.access" }', "$.duration_ms").with({
      statistic: "p95",
    });
    // Dagster's own event line for a run that failed, which the worker's
    // run processes write to the container's output (§889). Quoted, so the
    // whole term is matched rather than its parts.
    const workerRunFailures = counted("WorkerRunFailures", '"RUN_FAILURE"');
    // A page that threw in someone's browser, as the error page reports it
    // (§926; `routes/client_errors.py`). "stale" is a page from before a
    // deploy, which a reload fixes, and is not counted.
    const pageErrors = counted(
      "WebPageErrors",
      '{ $.logger = "anchor.client_error" && $.kind = "fault" }'
    );

    const alarm = (
      name: string,
      metric: cloudwatch.IMetric,
      threshold: number,
      comparison: cloudwatch.ComparisonOperator,
      periods: number,
      description: string
    ): void => {
      const made = new cloudwatch.Alarm(this, name, {
        metric,
        threshold,
        comparisonOperator: comparison,
        evaluationPeriods: periods,
        // A quiet API writes no lines, so no data is the ordinary state of
        // every log-derived metric here - not a fault.
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
        alarmDescription: description,
      });
      made.addAlarmAction(new actions.SnsAction(this.topic));
      made.addOkAction(new actions.SnsAction(this.topic));
      this.alarms.push(made);
    };
    const above = cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD;
    const atLeast = cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD;
    const below = cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD;

    alarm(
      "ApiErrorRate",
      new cloudwatch.MathExpression({
        // A rate rather than a count, so a busy hour is not an incident; and
        // nothing below twenty requests, so one failed call at 3am is not 100%.
        expression: "IF(requests >= 20, 100 * errors / requests, 0)",
        usingMetrics: { requests, errors: serverErrors },
        period: Duration.minutes(5),
        label: "API 5xx, % of requests",
      }),
      5, above, 2,
      "The API answered more than 5% of requests with a 5xx for ten minutes."
    );
    alarm(
      "ApiUnhandledError",
      unhandled, 1, atLeast, 1,
      "The API raised an unhandled error. Its log line on anchor.error carries the request id the 500 quoted."
    );
    alarm(
      "ApiLatency",
      latency, 2000, above, 3,
      "The API's p95 latency was over two seconds for fifteen minutes."
    );
    // §925: the web server too. Without a task every page is gone, the API
    // answering or not, and nothing was watching it.
    for (const [name, service] of [
      ["Api", props.apiService],
      ["Worker", props.workerService],
      ["Web", props.webService],
    ] as const) {
      alarm(
        `${name}NotRunning`,
        new cloudwatch.Metric({
          namespace: "ECS/ContainerInsights",
          metricName: "RunningTaskCount",
          dimensionsMap: { ClusterName: props.cluster.clusterName, ServiceName: service.serviceName },
          period: Duration.minutes(1),
          statistic: "Minimum",
        }),
        1, below, 3,
        `The ${name.toLowerCase()} service has had no running task for three minutes.`
      );
    }
    alarm(
      "WorkerRunsFailing",
      workerRunFailures, 3, atLeast, 1,
      "Three or more of the worker's scheduled runs failed in five minutes: a poll itself is " +
        "failing, every minute. A sync's or a model's own failure is recorded on it, not here. " +
        "The worker's log has Dagster's RUN_FAILURE lines with the error."
    );
    alarm(
      "WebPageErrors",
      pageErrors, 5, atLeast, 1,
      "Five or more pages failed in people's browsers in five minutes. Each is a line on " +
        "anchor.client_error with the page's path, its error and who saw it."
    );
    alarm(
      "ApiUnhealthyTargets",
      props.apiTargetGroup.metrics.unhealthyHostCount({ period: Duration.minutes(1) }),
      1, atLeast, 3,
      "An API task has failed the load balancer's health check for three minutes."
    );
    alarm(
      "WebUnhealthyTargets",
      props.webTargetGroup.metrics.unhealthyHostCount({ period: Duration.minutes(1) }),
      1, atLeast, 3,
      "A web task has failed the load balancer's health check for three minutes."
    );
    alarm(
      "DatabaseConnections",
      props.database.metricDatabaseConnections({ period: Duration.minutes(5), statistic: "Maximum" }),
      DATABASE_CONNECTIONS_ALARM, above, 2,
      `The database has held more than ${DATABASE_CONNECTIONS_ALARM} connections for ten minutes, ` +
        "four in five of what it allows. A new task may soon be refused one."
    );
    alarm(
      "DatabaseStorage",
      props.database.metricFreeStorageSpace({ period: Duration.minutes(5), statistic: "Minimum" }),
      2 * 1024 * 1024 * 1024, below, 1,
      "The database has less than 2 GiB of storage free."
    );
    alarm(
      "DatabaseCpu",
      props.database.metricCPUUtilization({ period: Duration.minutes(5) }),
      80, above, 3,
      "The database's CPU has been over 80% for fifteen minutes."
    );
  }
}

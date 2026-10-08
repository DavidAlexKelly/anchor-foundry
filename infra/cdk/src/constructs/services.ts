import { ArnFormat, Duration, Stack } from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as efs from "aws-cdk-lib/aws-efs";
import * as iam from "aws-cdk-lib/aws-iam";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as logs from "aws-cdk-lib/aws-logs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as cognito from "aws-cdk-lib/aws-cognito";
import { Construct } from "constructs";


/**
 * **Two of each request-serving task, and more under load** (§841). One task
 * was the whole API: a crash, an out-of-memory kill or a lost host was an
 * outage until ECS replaced it, and a busy hour had nowhere to go. Two keep
 * serving while one is replaced, spread across the VPC's zones; CPU scales
 * them out from there.
 *
 * The ceiling is the database's to set. Each API task holds up to 30
 * connections (a pool of 10 and 20 overflow, `apps/api/src/lib/db.py`), so six
 * is 180 of the roughly 450 a t4g.medium allows - room for the worker, the
 * migration Lambda and an operator besides.
 */
export const API_TASKS = { min: 2, max: 6 };
export const WEB_TASKS = { min: 2, max: 4 };
export const SCALE_AT_CPU_PERCENT = 60;

/**
 * **How much memory a task has, and how much of it one DuckDB may hold**
 * (§875; E.27). Every dataset operation opens its own DuckDB, which by default
 * takes 80% of what it can see: on a 1 GB API task, two profiles at once were
 * an out-of-memory kill of the task and every request on it.
 *
 * Now each connection is held to `DUCKDB_MEMORY_MIB` and spills past it to
 * local disk (`apps/api/src/lib/duck.py`). The limit governs DuckDB's buffers,
 * not the process, and §875 measured resident memory at up to one and a half
 * times it; so a task is sized for two such operations at once beside the
 * process itself, which scaling-check.ts holds. That took the API from 1 GB
 * to 2 GB, which on Fargate is about $3 a month a task: memory is the cheap
 * line of the bill.
 *
 * **The worker is sized by its runs, not by two operations (§894).** Its
 * schedules run (§883), up to four runs at once, two of them the jobs that
 * work datasets in its own process (`apps/worker/dagster.yaml`). §894
 * measured the daemon at about 290 MB and a run's process at about 160 MB,
 * so it went from 2 GB to 4 GB, about $6 a month.
 *
 * Why 512 MiB rather than less: §875's three-million-row join refused to run
 * under 384 MiB at two threads, and a user's query is held to 512 MB already
 * (`QUERY_MEMORY_LIMIT`).
 */
export const TASK_MEMORY_MIB = { api: 2048, worker: 4096 };
export const DUCKDB_MEMORY_MIB = 512;
export const DUCKDB_THREADS = 2;
/** How many operations the API lets hold DuckDB at once (§911). The task is
 * sized for this many; one more waits for a slot rather than taking memory
 * the task does not have (`apps/api/src/lib/duck.py`). */
export const API_DUCKDB_SLOTS = 2;
/** What a task's process holds besides DuckDB, allowed for when sizing. */
export const PROCESS_ALLOWANCE_MIB = 512;
/** One worker run's own process, besides its DuckDB (§894: measured 160 MB). */
export const WORKER_RUN_PROCESS_MIB = 256;

/**
 * **Each hop on a request's way in waits longer than the one in front of it**
 * (§918). CloudFront gives the load balancer `ORIGIN_READ_TIMEOUT_S` to start
 * answering; the load balancer keeps a quiet connection `ALB_IDLE_TIMEOUT_S`;
 * the API and the web server keep theirs `TARGET_KEEP_ALIVE_S`.
 *
 * Unset, the order was backwards at its last step. uvicorn and Next.js close
 * an idle connection after 5 seconds, and the load balancer, which keeps its
 * own for 60, would send the next request down one the server had just
 * closed: a 502 for a request nothing was wrong with, the failure AWS's own
 * guidance warns of, at random and more often under load. And CloudFront's
 * 30-second default answered a sync or a model run that took longer with a
 * 504 while the API carried on and finished it. 60 seconds is the most
 * CloudFront allows without a quota increase.
 */
/**
 * **How long the worker's Dagster daemon may go without a heartbeat** before
 * ECS replaces the task (§924). The worker has no load balancer, so nothing
 * asked whether it was alive: a daemon that hung, or a thread of it that died,
 * left a task ECS saw as running while no schedule fired - every scheduled
 * sync, export, model and cleanup stopped, and nothing said so. The daemons
 * beat every 30 seconds; five minutes is ten missed beats, which a busy tick
 * does not come near.
 */
export const WORKER_HEARTBEAT_TOLERANCE_S = 300;

export const ORIGIN_READ_TIMEOUT_S = 60;
export const ALB_IDLE_TIMEOUT_S = 75;
export const TARGET_KEEP_ALIVE_S = 90;

export interface ServicesProps {
  readonly vpc: ec2.IVpc;
  readonly dataBucket: s3.IBucket;
  readonly dbSecret: secretsmanager.ISecret;
  readonly appDbSecret: secretsmanager.ISecret;
  readonly databaseHost: string;
  readonly databasePort: string;
  readonly searchEndpoint: string;
  readonly userPool: cognito.IUserPool;
  readonly userPoolClientId: string;
  /** ECR image URIs pushed by the vendor account (spec §6 "Updates"). */
  readonly apiImage: string;
  readonly workerImage: string;
  readonly webImage: string;
  readonly imageTag: string;
  /** The security group in front of the VPC's interface endpoints. The
   * transform runner is allowed to reach these and nothing else. */
  readonly vpcEndpointSecurityGroup: ec2.ISecurityGroup;
  /** Set when objects live in the OpenSearch domain (§814): the API and the
   * worker are given its master user and read and write objects there.
   * Unset, both use Postgres - the two read the same pair of variables, so
   * they cannot disagree about where objects are. */
  readonly objectIndexSecret?: secretsmanager.ISecret;
  /** SHA-256, in hex, of the token the provisioner creates the first owner
   * with (§886). Set, the API's first-owner route refuses anyone else. */
  readonly bootstrapTokenHash?: string;
  /** Decision 0025's option B (§909): the load balancer is internal, in
   * private subnets, and admits only the VPC, where CloudFront's VPC origin
   * reaches it from. Unset, it is internet-facing, as every stack so far. */
  readonly internalLoadBalancer?: boolean;
}

/**
 * ECS Fargate services (spec §6): api, worker, web. Spec §10: "Least-privilege
 * IAM roles per ECS service - the API task role cannot do what the worker
 * task role can do." Concretely:
 *   - api:    read/write S3 data, read app-db secret, manage data-source
 *             secrets under anchor/connections/*, Cognito admin on the
 *             org's pool (invitations).
 *   - worker: read/write S3 data, read app-db secret, read connection
 *             secrets (to establish syncs). NO Cognito access.
 *   - web:    serves static assets; no AWS data permissions at all.
 */
export class ServicesConstruct extends Construct {
  public readonly cluster: ecs.Cluster;
  public readonly apiService: ecs.FargateService;
  public readonly workerService: ecs.FargateService;
  /** Run on demand by the worker, never as a long-running service: a
   * transform is a job, and a service would be a container sitting idle with
   * customer code in it. */
  public readonly transformRunnerTaskDefinition: ecs.FargateTaskDefinition;
  public readonly transformRunnerSecurityGroup: ec2.SecurityGroup;
  /** Shared working directory between the worker and the runner. Mounted by
   * the ECS agent, so the runner never authenticates to anything. */
  public readonly transformScratch: efs.FileSystem;
  public readonly webService: ecs.FargateService;
  public readonly alb: elbv2.ApplicationLoadBalancer;
  /** Every container's log stream, for the alarms that read it (§815). */
  public readonly logGroup: logs.LogGroup;
  public readonly apiTargetGroup: elbv2.ApplicationTargetGroup;

  constructor(scope: Construct, id: string, props: ServicesProps) {
    super(scope, id);
    const { vpc } = props;

    this.cluster = new ecs.Cluster(this, "Cluster", {
      vpc,
      // `containerInsights: true` before aws-cdk-lib 2.272 (§838); the same
      // cluster setting, by the property that is not deprecated.
      containerInsightsV2: ecs.ContainerInsights.ENABLED,
    });
    const logGroup = new logs.LogGroup(this, "Logs", { retention: logs.RetentionDays.ONE_MONTH });
    this.logGroup = logGroup;

    // ---- Task roles (least privilege per service, §10) ----------------------
    const apiTaskRole = new iam.Role(this, "ApiTaskRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      description: "Platform API task role",
    });
    props.dataBucket.grantReadWrite(apiTaskRole);
    props.appDbSecret.grantRead(apiTaskRole);
    // Data source credentials live under a dedicated prefix; the API may
    // create/read/rotate them but nothing else in Secrets Manager (§5, §10).
    // **The prefix the code writes** (apps/api/src/services/secrets.py's
    // SECRET_PREFIX): this named `platform/connections/*` while every secret
    // was created as `anchor/connections/<id>`, so a deployed stack refused
    // every connection's credentials (§846). And this stack's own region and
    // account, not any.
    const connectionSecrets = Stack.of(this).formatArn({
      service: "secretsmanager",
      resource: "secret",
      resourceName: "anchor/connections/*",
      arnFormat: ArnFormat.COLON_RESOURCE_NAME,
    });
    apiTaskRole.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          "secretsmanager:CreateSecret",
          "secretsmanager:GetSecretValue",
          "secretsmanager:PutSecretValue",
          "secretsmanager:DeleteSecret",
          "secretsmanager:TagResource",
        ],
        resources: [connectionSecrets],
      })
    );
    apiTaskRole.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          "cognito-idp:AdminCreateUser",
          "cognito-idp:AdminDisableUser",
          "cognito-idp:AdminEnableUser",
          "cognito-idp:AdminGetUser",
          "cognito-idp:AdminResetUserPassword",
        ],
        resources: [props.userPool.userPoolArn],
      })
    );

    const workerTaskRole = new iam.Role(this, "WorkerTaskRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      description: "Platform worker task role - deliberately narrower than API (no Cognito)",
    });
    props.dataBucket.grantReadWrite(workerTaskRole);
    props.appDbSecret.grantRead(workerTaskRole);
    workerTaskRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["secretsmanager:GetSecretValue"],
        resources: [connectionSecrets],
      })
    );
    // No Athena (§846). Spec §7's large-dataset path is not built: nothing
    // calls Athena and no `platform` workgroup exists, so the grant named
    // a resource that was never there. Add it back with the code that uses it.

    // ---- Transform scratch: how anything reaches a task with no credentials --
    // The transport decision 0004 left open (STATUS.md §65). With an empty task
    // role and no egress, inputs cannot arrive by S3 - the runner cannot reach
    // it, deliberately. A shared filesystem can, because **the ECS agent
    // performs the mount, not the container**: the runner authenticates to
    // nothing and its role stays empty, which is the property the whole
    // decision rests on.
    //
    // Cost: EFS is charged per GB stored with no baseline, and this holds one
    // run's inputs at a time. The lifecycle policy moves anything left behind
    // to infrequent access rather than letting an abandoned run accrue.
    const scratchSecurityGroup = new ec2.SecurityGroup(this, "TransformScratchSg", {
      vpc: props.vpc,
      description: "Transform scratch EFS - reachable from the worker and the runner only",
      allowAllOutbound: false,
    });
    const scratch = new efs.FileSystem(this, "TransformScratch", {
      vpc: props.vpc,
      securityGroup: scratchSecurityGroup,
      encrypted: true,
      lifecyclePolicy: efs.LifecyclePolicy.AFTER_7_DAYS,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
    });
    // An access point rather than the filesystem root: it pins the uid/gid and
    // a directory, so a transform cannot read another run's staging area by
    // walking up one level.
    const scratchAccessPoint = scratch.addAccessPoint("TransformScratchAp", {
      path: "/runs",
      createAcl: { ownerUid: "1000", ownerGid: "1000", permissions: "750" },
      posixUser: { uid: "1000", gid: "1000" },
    });
    this.transformScratch = scratch;

    // ---- Transform runner (decision 0004) -----------------------------------
    // Customer-authored Python runs here and nowhere else. Two properties, and
    // the order matters because the first is the control and the second is the
    // blast radius.
    //
    // **The role grants nothing.** ECS hands a task its role credentials over
    // the network from 169.254.170.2, which is link-local and not something a
    // security group can filter - so "no egress" does not stop a transform
    // *obtaining* credentials. What stops it mattering is that these ones can
    // do nothing: no bucket, no secret, no Athena. Compare the worker's role,
    // which can read the whole data bucket and the app database secret, and
    // whose secret would let any holder set app.service='worker' and read
    // every workspace in the deployment (db 0006). That is why customer code
    // may not run as the worker.
    //
    // **Egress is closed except to the VPC endpoints below.** A transform
    // needs no network - its inputs arrive as files and its output is a file -
    // so this is what turns a mistake into a contained one rather than an
    // exfiltration route, in a product whose premise is that data stays inside
    // the customer's boundary.
    const runnerTaskRole = new iam.Role(this, "TransformRunnerTaskRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      description:
        "Customer transform code runs as this. Deliberately holds no policies - " +
        "see docs/decisions/0004-running-customer-code.md",
    });

    this.transformRunnerSecurityGroup = new ec2.SecurityGroup(this, "TransformRunnerSg", {
      vpc: props.vpc,
      description: "Transform runner - no egress except AWS endpoints for image pull and logs",
      // CDK's default is an allow-all egress rule, which is the thing this
      // security group exists to not have.
      allowAllOutbound: false,
    });
    // Fargate pulls the image and ships logs over the task ENI, so both are
    // subject to this group. Without a path to the endpoints the task cannot
    // start at all - the container never runs and CloudWatch shows an empty
    // log stream, which is the same symptom as the arm64 image problem in
    // STATUS.md §20 and just as unhelpful.
    this.transformRunnerSecurityGroup.addEgressRule(
      props.vpcEndpointSecurityGroup,
      ec2.Port.tcp(443),
      "ECR, S3 and CloudWatch Logs via VPC endpoints - no route to the internet"
    );
    // NFS to the scratch filesystem. Still not a route out: the only two
    // destinations this group can reach are AWS endpoints inside the VPC and
    // one filesystem.
    this.transformRunnerSecurityGroup.addEgressRule(
      scratchSecurityGroup,
      ec2.Port.tcp(2049),
      "Transform scratch (EFS) - staged inputs in, output back"
    );
    scratchSecurityGroup.addIngressRule(
      this.transformRunnerSecurityGroup,
      ec2.Port.tcp(2049),
      "Transform runner"
    );

    const runnerTaskDef = new ecs.FargateTaskDefinition(this, "TransformRunnerTaskDef", {
      cpu: 1024,
      memoryLimitMiB: 2048,
      taskRole: runnerTaskRole,
      volumes: [
        {
          name: "scratch",
          efsVolumeConfiguration: {
            fileSystemId: scratch.fileSystemId,
            transitEncryption: "ENABLED",
            authorizationConfig: { accessPointId: scratchAccessPoint.accessPointId, iam: "DISABLED" },
          },
        },
      ],
    });
    runnerTaskDef.obtainExecutionRole().addManagedPolicy(
      iam.ManagedPolicy.fromAwsManagedPolicyName("service-role/AmazonECSTaskExecutionRolePolicy")
    );
    runnerTaskDef.addContainer("runner", {
      image: ecs.ContainerImage.fromRegistry(`${props.workerImage}:${props.imageTag}`),
      logging: ecs.LogDrivers.awsLogs({ logGroup, streamPrefix: "transform-runner" }),
      // No commonEnv and no dbSecretEnv. The runner is handed its inputs as
      // files by whoever started it; it has no use for a database host and no
      // business holding a database password.
      environment: {
        // Belt and braces behind the empty role: stops the AWS SDKs inside the
        // container from reaching for instance metadata at all. Not the
        // control - the role is - but it removes a confusing failure mode.
        AWS_EC2_METADATA_DISABLED: "true",
        // Matches transform_runner.WORK_DIR_ENV. Set explicitly rather than
        // relying on the module's default, so the mount path and the code that
        // reads it are stated in the same place.
        ANCHOR_TRANSFORM_WORKDIR: "/work",
      },
      command: ["python", "-m", "anchor_worker.transform_runner"],
    }).addMountPoints({
      containerPath: "/work",
      sourceVolume: "scratch",
      // The runner writes its output and result file here, so this cannot be
      // read-only - and the access point is what keeps one run out of
      // another's directory.
      readOnly: false,
    });
    this.transformRunnerTaskDefinition = runnerTaskDef;

    const webTaskRole = new iam.Role(this, "WebTaskRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      description: "Platform web task role - no data permissions",
    });

    // ---- Shared env ---------------------------------------------------------
    const commonEnv = {
      OPENSEARCH_ENDPOINT: `https://${props.searchEndpoint}`,
      S3_DATA_BUCKET: props.dataBucket.bucketName,
      COGNITO_USER_POOL_ID: props.userPool.userPoolId,
      COGNITO_CLIENT_ID: props.userPoolClientId,
      // apps/api's Settings defaults this to eu-west-2 (its own local-dev
      // default) if unset — real deployments must set it explicitly, or JWT
      // verification builds the JWKS URL for the wrong region entirely.
      COGNITO_REGION: Stack.of(this).region,
      PLATFORM_VERSION: props.imageTag,
      // Host/port aren't secret; the password is (below). Both apps assemble
      // their own connection string from these parts at startup rather than
      // receiving one ready-made — CDK can't embed a Secrets Manager value
      // inside a single plain env var.
      DATABASE_HOST: props.databaseHost,
      DATABASE_PORT: props.databasePort,
      DATABASE_NAME: "platform",
    };
    const dbSecretEnv = {
      // App connects as the RLS-subject role; the master secret is used only
      // by the migration task, never by the running services (db 0006).
      DATABASE_USERNAME: ecs.Secret.fromSecretsManager(props.appDbSecret, "username"),
      DATABASE_PASSWORD: ecs.Secret.fromSecretsManager(props.appDbSecret, "password"),
    };

    // Only the two services that touch objects, and only when asked (§814).
    const objectIndexEnv: Record<string, string> = {};
    if (props.objectIndexSecret) {
      props.objectIndexSecret.grantRead(apiTaskRole);
      props.objectIndexSecret.grantRead(workerTaskRole);
      objectIndexEnv.OPENSEARCH_SECRET_ARN = props.objectIndexSecret.secretArn;
    }

    const makeService = (
      name: string,
      image: string,
      role: iam.Role,
      opts: {
        cpu: number;
        memory: number;
        port?: number;
        command?: string[];
        /** Mount the transform scratch filesystem. Only the worker does: it is
         * the side that stages a run's inputs and reads its result back. */
        mountScratch?: boolean;
        /** Env this service needs and the others do not. */
        extraEnv?: Record<string, string>;
        /** How ECS asks the container whether it is alive, for a service no
         * load balancer health-checks. */
        healthCheck?: ecs.HealthCheck;
        /** How many tasks, scaled on CPU between the two (§841). Omitted, one
         * task and no scaling - which only the worker should be. */
        tasks?: { min: number; max: number };
      }
    ): ecs.FargateService => {
      const taskDef = new ecs.FargateTaskDefinition(this, `${name}TaskDef`, {
        cpu: opts.cpu,
        memoryLimitMiB: opts.memory,
        taskRole: role,
        volumes: opts.mountScratch
          ? [
              {
                name: "scratch",
                efsVolumeConfiguration: {
                  fileSystemId: scratch.fileSystemId,
                  transitEncryption: "ENABLED",
                  authorizationConfig: {
                    accessPointId: scratchAccessPoint.accessPointId,
                    iam: "DISABLED",
                  },
                },
              },
            ]
          : undefined,
      });
      // ContainerImage.fromRegistry (below) takes a plain URL string, not an
      // IRepository, so CDK has nothing to grant ECR pull permissions from —
      // it only auto-grants when built via fromEcrRepository(). Without this,
      // the execution role has zero ECR permissions and every task fails to
      // even pull its image (confirmed: empty CloudWatch log streams, since
      // the container never starts). The synth-time ecrImageRequiresPolicy
      // warning is the correct signal for exactly this gap.
      taskDef.obtainExecutionRole().addManagedPolicy(
        iam.ManagedPolicy.fromAwsManagedPolicyName("service-role/AmazonECSTaskExecutionRolePolicy")
      );
      const container = taskDef.addContainer(name, {
        image: ecs.ContainerImage.fromRegistry(image),
        logging: ecs.LogDrivers.awsLogs({ logGroup, streamPrefix: name }),
        environment: { ...commonEnv, ...(opts.extraEnv ?? {}) },
        secrets: name === "web" ? undefined : dbSecretEnv,
        command: opts.command,
        healthCheck: opts.healthCheck,
      });
      if (opts.port !== undefined) {
        container.addPortMappings({ containerPort: opts.port });
      }
      if (opts.mountScratch) {
        container.addMountPoints({
          containerPath: "/transform-scratch",
          sourceVolume: "scratch",
          readOnly: false,
        });
      }
      const service = new ecs.FargateService(this, `${name}Service`, {
        cluster: this.cluster,
        taskDefinition: taskDef,
        desiredCount: opts.tasks?.min ?? 1,
        vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS }, // §10
        circuitBreaker: { rollback: true },
        minHealthyPercent: 100, // zero-downtime rolling updates (spec §6)
        maxHealthyPercent: 200,
      });
      if (opts.tasks) {
        const scaling = service.autoScaleTaskCount({
          minCapacity: opts.tasks.min,
          maxCapacity: opts.tasks.max,
        });
        scaling.scaleOnCpuUtilization(`${name}Cpu`, {
          targetUtilizationPercent: SCALE_AT_CPU_PERCENT,
        });
      }
      return service;
    };

    const duckdbEnv = {
      DUCKDB_MEMORY_LIMIT: `${DUCKDB_MEMORY_MIB}MiB`,
      DUCKDB_THREADS: String(DUCKDB_THREADS),
    };
    this.apiService = makeService("api", `${props.apiImage}:${props.imageTag}`, apiTaskRole, {
      cpu: 512,
      memory: TASK_MEMORY_MIB.api,
      port: 8000,
      tasks: API_TASKS,
      // A listener's ingress allowlist (§520) checks the sender's address,
      // read from X-Forwarded-For this many entries from the right. uvicorn's
      // own forwarded-allow-ips is left alone, because trusting "*" there
      // takes the *first* entry, which the sender writes.
      //
      // **One hop is the load balancer's entry, and through CloudFront that
      // is CloudFront's address, not the sender's (§850).** CloudFront writes
      // the sender's, one further left, so two would be right for traffic
      // that came through it. But the load balancer is public (decision
      // 0025), and a request sent to it directly would supply that entry
      // itself. Until the load balancer is reachable only through CloudFront,
      // one hop is the only entry nobody can forge, and an allowlist refuses
      // senders that come through CloudFront. stack-check.ts holds the two
      // together.
      extraEnv: {
        // Public, a request can reach the load balancer directly and write
        // every entry left of the load balancer's own, so one hop is all that
        // can be trusted (§850). Internal, CloudFront's entry - the sender's -
        // is the second from the right, and nobody else can write it (§909).
        LISTENER_PROXY_HOPS: props.internalLoadBalancer ? "2" : "1",
        ...objectIndexEnv,
        ...duckdbEnv,
        // The API's operations share one process; the worker's runs are each
        // their own, held to four at once by Dagster (§888).
        DUCKDB_SLOTS: String(API_DUCKDB_SLOTS),
        // uvicorn reads its options from UVICORN_*; seconds.
        UVICORN_TIMEOUT_KEEP_ALIVE: String(TARGET_KEEP_ALIVE_S),
        // §923: no `server: uvicorn` on every answer, naming the software
        // to anyone matching it against advisories.
        UVICORN_SERVER_HEADER: "false",
        ...(props.bootstrapTokenHash ? { BOOTSTRAP_TOKEN_SHA256: props.bootstrapTokenHash } : {}),
      },
    });
    // Everything anchor_worker/transform_dispatch.py needs to find the runner.
    // Passed as configuration rather than discovered at run time: a worker that
    // guessed its own cluster would guess wrong in a stack it does not own, and
    // the failure would be a RunTask into somebody else's cluster.
    const transformRunnerEnv = {
      ANCHOR_TRANSFORM_SCRATCH: "/transform-scratch",
      ANCHOR_TRANSFORM_CLUSTER: this.cluster.clusterName,
      ANCHOR_TRANSFORM_TASK_DEFINITION: runnerTaskDef.taskDefinitionArn,
      ANCHOR_TRANSFORM_SUBNETS: vpc
        .selectSubnets({ subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS })
        .subnetIds.join(","),
      ANCHOR_TRANSFORM_SECURITY_GROUPS: this.transformRunnerSecurityGroup.securityGroupId,
    };
    // **One worker, always, and not scaled** (§841): it runs the Dagster
    // daemon, which fires every schedule - a second task would run each
    // scheduled sync, export and model twice.
    this.workerService = makeService("worker", `${props.workerImage}:${props.imageTag}`, workerTaskRole, {
      cpu: 1024,
      memory: TASK_MEMORY_MIB.worker,
      mountScratch: true,
      extraEnv: { ...transformRunnerEnv, ...objectIndexEnv, ...duckdbEnv },
      // §924: Dagster's own check of its daemons' heartbeats, read from the
      // instance on the task's disk. About two seconds; a deploy's new task
      // has five minutes to start beating before a miss counts. While old
      // and new both run, `jobs/claims.py` keeps each due run to one of them.
      healthCheck: {
        command: ["CMD-SHELL",
          `DAGSTER_DAEMON_HEARTBEAT_TOLERANCE=${WORKER_HEARTBEAT_TOLERANCE_S} dagster-daemon liveness-check`],
        interval: Duration.seconds(60),
        timeout: Duration.seconds(30),
        retries: 3,
        startPeriod: Duration.seconds(300),
      },
    });

    // ---- Permission to dispatch, and nothing more ---------------------------
    // Scoped to one task definition and one cluster. A wildcard here would let
    // the worker start any task in the account.
    workerTaskRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["ecs:RunTask"],
        resources: [runnerTaskDef.taskDefinitionArn],
        conditions: { ArnEquals: { "ecs:cluster": this.cluster.clusterArn } },
      })
    );
    workerTaskRole.addToPolicy(
      new iam.PolicyStatement({
        // The task's ARN is not known until RunTask returns, so this cannot be
        // narrowed past the cluster - which the condition pins.
        actions: ["ecs:DescribeTasks", "ecs:StopTask"],
        resources: [`arn:aws:ecs:${Stack.of(this).region}:${Stack.of(this).account}:task/*`],
        conditions: { ArnEquals: { "ecs:cluster": this.cluster.clusterArn } },
      })
    );
    // **The one that would matter if it were wrong.** RunTask requires
    // iam:PassRole for the roles in the task definition, and an unscoped
    // PassRole is a privilege escalation, not a convenience: the worker could
    // register a task definition naming any role in the account and start a
    // container as it. Named exactly, so the only roles the worker can hand to
    // a task are the runner's empty one and the execution role that pulls its
    // image.
    workerTaskRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["iam:PassRole"],
        resources: [runnerTaskRole.roleArn, runnerTaskDef.obtainExecutionRole().roleArn],
        conditions: { StringEquals: { "iam:PassedToService": "ecs-tasks.amazonaws.com" } },
      })
    );
    // The worker stages a run's inputs and reads its result back, so it needs
    // the mount too. Granted from the service rather than by hand: CDK creates
    // the service's security group, and a hand-written rule would name a group
    // that does not exist yet.
    scratch.connections.allowDefaultPortFrom(
      this.workerService,
      "Worker stages transform inputs and collects results"
    );
    this.webService = makeService("web", `${props.webImage}:${props.imageTag}`, webTaskRole, {
      cpu: 256,
      memory: 512,
      port: 3000,
      tasks: WEB_TASKS,
      // Next.js's standalone server reads this; milliseconds.
      extraEnv: { KEEP_ALIVE_TIMEOUT: String(TARGET_KEEP_ALIVE_S * 1000) },
    });

    // ---- ALB: the only public-facing component (§10) ------------------------
    const internal = props.internalLoadBalancer === true;
    this.alb = new elbv2.ApplicationLoadBalancer(this, "Alb", {
      vpc,
      internetFacing: !internal,
      vpcSubnets: { subnetType: internal ? ec2.SubnetType.PRIVATE_WITH_EGRESS : ec2.SubnetType.PUBLIC },
      idleTimeout: Duration.seconds(ALB_IDLE_TIMEOUT_S),
    });
    // Public: HTTP only, and open to the internet. This said the control plane
    // would attach a certificate and an HTTPS listener once a customer
    // subdomain was issued; nothing does, so CloudFront reaches this in plain
    // HTTP and so can anyone else. Decision 0025 (roadmap E.11).
    //
    // Internal (option B, §909): open to the VPC only. CloudFront's VPC origin
    // reaches it through network interfaces it places in the VPC, so its
    // traffic comes from inside the VPC's range, and a fixed range needs no
    // lookup of the origin's security group, which CloudFront creates itself.
    const listener = this.alb.addListener("Http", { port: 80, open: !internal });
    if (internal) {
      listener.connections.allowFrom(
        ec2.Peer.ipv4(vpc.vpcCidrBlock), ec2.Port.tcp(80),
        "CloudFront's VPC origin, from inside the VPC (decision 0025)");
    }
    listener.addTargets("Web", {
      port: 3000,
      protocol: elbv2.ApplicationProtocol.HTTP,
      targets: [this.webService],
      healthCheck: { path: "/", healthyHttpCodes: "200-399" },
    });
    this.apiTargetGroup = listener.addTargets("Api", {
      priority: 10,
      conditions: [elbv2.ListenerCondition.pathPatterns(["/api/*", "/graphql"])],
      port: 8000,
      protocol: elbv2.ApplicationProtocol.HTTP,
      targets: [this.apiService],
      healthCheck: { path: "/api/health", healthyHttpCodes: "200" },
      deregistrationDelay: Duration.seconds(15),
    });
  }
}

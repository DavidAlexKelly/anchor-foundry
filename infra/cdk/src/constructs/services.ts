import { Duration, Stack } from "aws-cdk-lib";
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

export interface ServicesProps {
  readonly vpc: ec2.IVpc;
  readonly dataBucket: s3.IBucket;
  readonly dbSecret: secretsmanager.ISecret;
  readonly appDbSecret: secretsmanager.ISecret;
  readonly databaseHost: string;
  readonly databasePort: string;
  readonly redisEndpoint: string;
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
}

/**
 * ECS Fargate services (spec §6): api, worker, web. Spec §10: "Least-privilege
 * IAM roles per ECS service - the API task role cannot do what the worker
 * task role can do." Concretely:
 *   - api:    read/write S3 data, read app-db secret, manage data-source
 *             secrets under platform/connections/*, Cognito admin on the
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

  constructor(scope: Construct, id: string, props: ServicesProps) {
    super(scope, id);
    const { vpc } = props;

    this.cluster = new ecs.Cluster(this, "Cluster", { vpc, containerInsights: true });
    const logGroup = new logs.LogGroup(this, "Logs", { retention: logs.RetentionDays.ONE_MONTH });

    // ---- Task roles (least privilege per service, §10) ----------------------
    const apiTaskRole = new iam.Role(this, "ApiTaskRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      description: "Platform API task role",
    });
    props.dataBucket.grantReadWrite(apiTaskRole);
    props.appDbSecret.grantRead(apiTaskRole);
    // Data source credentials live under a dedicated prefix; the API may
    // create/read/rotate them but nothing else in Secrets Manager (§5, §10).
    apiTaskRole.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          "secretsmanager:CreateSecret",
          "secretsmanager:GetSecretValue",
          "secretsmanager:PutSecretValue",
          "secretsmanager:DeleteSecret",
          "secretsmanager:TagResource",
        ],
        resources: [
          `arn:aws:secretsmanager:*:*:secret:platform/connections/*`,
        ],
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
        resources: [`arn:aws:secretsmanager:*:*:secret:platform/connections/*`],
      })
    );
    // Athena for large-dataset transforms (spec §7); scoped to the platform workgroup.
    workerTaskRole.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          "athena:StartQueryExecution",
          "athena:GetQueryExecution",
          "athena:GetQueryResults",
          "athena:StopQueryExecution",
        ],
        resources: [`arn:aws:athena:*:*:workgroup/platform`],
      })
    );

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
      REDIS_URL: `rediss://${props.redisEndpoint}:6379/0`,
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
      return new ecs.FargateService(this, `${name}Service`, {
        cluster: this.cluster,
        taskDefinition: taskDef,
        desiredCount: 1,
        vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS }, // §10
        circuitBreaker: { rollback: true },
        minHealthyPercent: 100, // zero-downtime rolling updates (spec §6)
        maxHealthyPercent: 200,
      });
    };

    this.apiService = makeService("api", `${props.apiImage}:${props.imageTag}`, apiTaskRole, {
      cpu: 512,
      memory: 1024,
      port: 8000,
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
    this.workerService = makeService("worker", `${props.workerImage}:${props.imageTag}`, workerTaskRole, {
      cpu: 1024,
      memory: 2048,
      mountScratch: true,
      extraEnv: transformRunnerEnv,
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
    });

    // ---- ALB: the only public-facing component (§10) ------------------------
    this.alb = new elbv2.ApplicationLoadBalancer(this, "Alb", {
      vpc,
      internetFacing: true,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
    });
    // HTTP listener only in the synth template; the control plane attaches the
    // ACM certificate + HTTPS listener once the customer subdomain is issued
    // (Route 53 + ACM, spec §7). HTTP-to-HTTPS redirect is added at that point.
    const listener = this.alb.addListener("Http", { port: 80, open: true });
    listener.addTargets("Web", {
      port: 3000,
      protocol: elbv2.ApplicationProtocol.HTTP,
      targets: [this.webService],
      healthCheck: { path: "/", healthyHttpCodes: "200-399" },
    });
    listener.addTargets("Api", {
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

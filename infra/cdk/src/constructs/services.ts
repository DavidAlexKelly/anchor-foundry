import { Duration, Stack } from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecs from "aws-cdk-lib/aws-ecs";
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

    const runnerTaskDef = new ecs.FargateTaskDefinition(this, "TransformRunnerTaskDef", {
      cpu: 1024,
      memoryLimitMiB: 2048,
      taskRole: runnerTaskRole,
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
      },
      command: ["python", "-m", "anchor_worker.transform_runner"],
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
      opts: { cpu: number; memory: number; port?: number; command?: string[] }
    ): ecs.FargateService => {
      const taskDef = new ecs.FargateTaskDefinition(this, `${name}TaskDef`, {
        cpu: opts.cpu,
        memoryLimitMiB: opts.memory,
        taskRole: role,
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
        environment: commonEnv,
        secrets: name === "web" ? undefined : dbSecretEnv,
        command: opts.command,
      });
      if (opts.port !== undefined) {
        container.addPortMappings({ containerPort: opts.port });
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
    this.workerService = makeService("worker", `${props.workerImage}:${props.imageTag}`, workerTaskRole, {
      cpu: 1024,
      memory: 2048,
    });
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

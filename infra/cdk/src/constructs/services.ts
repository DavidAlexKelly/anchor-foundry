import { Duration } from "aws-cdk-lib";
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
  readonly redisEndpoint: string;
  readonly searchEndpoint: string;
  readonly userPool: cognito.IUserPool;
  readonly userPoolClientId: string;
  /** ECR image URIs pushed by the vendor account (spec §6 "Updates"). */
  readonly apiImage: string;
  readonly workerImage: string;
  readonly webImage: string;
  readonly imageTag: string;
}

/**
 * ECS Fargate services (spec §6): api, worker, web. Spec §10: "Least-privilege
 * IAM roles per ECS service — the API task role cannot do what the worker
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
      description: "Platform worker task role — deliberately narrower than API (no Cognito)",
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

    const webTaskRole = new iam.Role(this, "WebTaskRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      description: "Platform web task role — no data permissions",
    });

    // ---- Shared env ---------------------------------------------------------
    const commonEnv = {
      REDIS_URL: `rediss://${props.redisEndpoint}:6379/0`,
      OPENSEARCH_ENDPOINT: `https://${props.searchEndpoint}`,
      S3_DATA_BUCKET: props.dataBucket.bucketName,
      COGNITO_USER_POOL_ID: props.userPool.userPoolId,
      COGNITO_CLIENT_ID: props.userPoolClientId,
      PLATFORM_VERSION: props.imageTag,
    };
    const dbSecretEnv = {
      // App connects as the RLS-subject role; the master secret is used only
      // by the migration task, never by the running services (db 0006).
      DATABASE_CREDENTIALS: ecs.Secret.fromSecretsManager(props.appDbSecret),
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

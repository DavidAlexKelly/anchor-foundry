import { CfnOutput, Stack, StackProps, Tags } from "aws-cdk-lib";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import * as cloudtrail from "aws-cdk-lib/aws-cloudtrail";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as guardduty from "aws-cdk-lib/aws-guardduty";
import * as wafv2 from "aws-cdk-lib/aws-wafv2";
import { Construct } from "constructs";
import { AuthConstruct } from "../constructs/auth";
import { DataStoresConstruct } from "../constructs/data-stores";
import { MigrationTriggerConstruct } from "../constructs/migration";
import { MonitoringConstruct } from "../constructs/monitoring";
import { ServicesConstruct } from "../constructs/services";
import { webAclRules } from "../constructs/waf";

export interface CustomerStackProps extends StackProps {
  readonly orgSlug: string;
  readonly platformUrl: string;
  readonly vendorEcrRegistry: string; // e.g. 123456789012.dkr.ecr.eu-west-2.amazonaws.com
  readonly imageTag: string;
  /** See DataStoresConstruct - defaults to true, only ever overridden for
   * throwaway dry-run stacks (app.ts's `deletionProtection` context flag). */
  readonly deletionProtection?: boolean;
  /** Where objects live: "postgres" (the default) or "opensearch", after the
   * cutover in docs/deploying.md (§814; app.ts's `objectStore` context). */
  readonly objectStore?: "postgres" | "opensearch";
  /** Subscribed to the stack's alarms (§815; app.ts's `alarmEmail` context). */
  readonly alarmEmail?: string;
}

/**
 * The full platform stack deployed into the CUSTOMER's AWS account
 * (spec §6 "What Runs Where"). Provisioned by the control plane via the
 * bootstrap role; runs day-to-day under the minimal-privilege roles defined
 * here, never under the bootstrap role.
 */
export class CustomerStack extends Stack {
  constructor(scope: Construct, id: string, props: CustomerStackProps) {
    super(scope, id, props);

    // §12: every resource tagged for cost transparency mapping.
    Tags.of(this).add("platform:customer", props.orgSlug);
    Tags.of(this).add("platform:component", "core");

    // ---- Network: private subnets, only the ALB is public (§10) -------------
    const vpc = new ec2.Vpc(this, "Vpc", {
      maxAzs: 2,
      natGateways: 1,
      subnetConfiguration: [
        { name: "public", subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
        { name: "private", subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS, cidrMask: 20 },
      ],
    });

    // ---- VPC endpoints: how a no-egress task still starts -------------------
    // The transform runner has no route to the internet (decision 0004), and
    // Fargate pulls its image and ships its logs over the task ENI - so
    // without these it cannot start, and the symptom is an empty CloudWatch
    // log stream, exactly like the arm64 image problem in STATUS.md §20.
    //
    // Cost, stated rather than discovered on a bill: three interface endpoints
    // at roughly $7-8 each per month, per deployment. The gateway endpoint for
    // S3 is free. That is the price of customer code that cannot phone home,
    // in a product whose premise is that data stays inside the customer's
    // account.
    const vpcEndpointSecurityGroup = new ec2.SecurityGroup(this, "VpcEndpointSg", {
      vpc,
      description: "AWS interface endpoints reachable from private subnets",
      allowAllOutbound: false,
    });
    vpcEndpointSecurityGroup.addIngressRule(
      ec2.Peer.ipv4(vpc.vpcCidrBlock),
      ec2.Port.tcp(443),
      "HTTPS from inside the VPC"
    );
    for (const [id, service] of [
      ["EcrApiEndpoint", ec2.InterfaceVpcEndpointAwsService.ECR],
      ["EcrDockerEndpoint", ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER],
      ["LogsEndpoint", ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS],
    ] as const) {
      vpc.addInterfaceEndpoint(id, {
        service,
        securityGroups: [vpcEndpointSecurityGroup],
        subnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      });
    }
    // Image *layers* come from S3, not from the ECR API. A gateway endpoint is
    // a route-table entry rather than an ENI, so it is free and it is also the
    // one people forget - leaving a pull that authenticates and then hangs.
    vpc.addGatewayEndpoint("S3Endpoint", { service: ec2.GatewayVpcEndpointAwsService.S3 });

    // ---- Security monitoring: enabled by default (§10) ----------------------
    new cloudtrail.Trail(this, "Trail", {
      isMultiRegionTrail: true,
      includeGlobalServiceEvents: true,
      enableFileValidation: true,
    });
    new guardduty.CfnDetector(this, "GuardDuty", { enable: true });

    // ---- Stateful stores ----------------------------------------------------
    const data = new DataStoresConstruct(this, "Data", {
      vpc,
      orgSlug: props.orgSlug,
      deletionProtection: props.deletionProtection,
      objectIndex: props.objectStore === "opensearch",
    });
    Tags.of(data.dataBucket).add("platform:component", "storage");
    Tags.of(data.database).add("platform:component", "database");
    Tags.of(data.search).add("platform:component", "object-search");

    // ---- Auth ---------------------------------------------------------------
    const auth = new AuthConstruct(this, "Auth", {
      orgSlug: props.orgSlug,
      platformUrl: props.platformUrl,
    });

    // ---- Schema migrations: run once per deploy, after the database exists
    // and before any service that depends on its schema starts (§17) --------
    const migration = new MigrationTriggerConstruct(this, "Migration", {
      vpc,
      database: data.database,
      dbSecret: data.dbSecret,
      appDbSecret: data.appDbSecret,
    });

    // ---- Compute ------------------------------------------------------------
    const services = new ServicesConstruct(this, "Services", {
      vpc,
      vpcEndpointSecurityGroup,
      dataBucket: data.dataBucket,
      dbSecret: data.dbSecret,
      appDbSecret: data.appDbSecret,
      databaseHost: data.database.instanceEndpoint.hostname,
      databasePort: data.database.instanceEndpoint.port.toString(),
      searchEndpoint: data.search.domainEndpoint,
      userPool: auth.userPool,
      userPoolClientId: auth.userPoolClient.userPoolClientId,
      apiImage: `${props.vendorEcrRegistry}/platform-api`,
      workerImage: `${props.vendorEcrRegistry}/platform-worker`,
      webImage: `${props.vendorEcrRegistry}/platform-web`,
      imageTag: props.imageTag,
      objectIndexSecret: props.objectStore === "opensearch" ? data.searchMasterSecret : undefined,
    });
    Tags.of(services.apiService).add("platform:component", "app-server");
    Tags.of(services.workerService).add("platform:component", "pipeline-runs");

    // The schema must exist before either service that reads/writes it starts.
    migration.trigger.executeBefore(services.apiService, services.workerService);

    // Network paths: only the services may reach the stores.
    // Descriptions use "to" rather than "->": AWS rejects security group
    // rule descriptions containing characters outside
    // a-zA-Z0-9. _-:/()#,@[]+=&;{}!$* (no < or >).
    data.database.connections.allowFrom(services.apiService, ec2.Port.tcp(5432), "api to postgres");
    data.database.connections.allowFrom(services.workerService, ec2.Port.tcp(5432), "worker to postgres");
    data.search.connections.allowFrom(services.apiService, ec2.Port.tcp(443), "api to opensearch");
    data.search.connections.allowFrom(services.workerService, ec2.Port.tcp(443), "worker to opensearch");

    // ---- Alarms on what the services write and report (§815) --------------
    const monitoring = new MonitoringConstruct(this, "Monitoring", {
      logGroup: services.logGroup,
      cluster: services.cluster,
      apiService: services.apiService,
      workerService: services.workerService,
      apiTargetGroup: services.apiTargetGroup,
      database: data.database,
      alarmEmail: props.alarmEmail,
    });

    // ---- WAF on the ALB with AWS managed rule sets (§10) --------------------
    const waf = new wafv2.CfnWebACL(this, "Waf", {
      scope: "REGIONAL",
      defaultAction: { allow: {} },
      visibilityConfig: {
        cloudWatchMetricsEnabled: true,
        metricName: "platform-waf",
        sampledRequestsEnabled: true,
      },
      // What the two managed sets block, and the six rules that only count
      // here because they refuse the platform's own data: constructs/waf.ts.
      rules: webAclRules(),
    });
    new wafv2.CfnWebACLAssociation(this, "WafAssoc", {
      resourceArn: services.alb.loadBalancerArn,
      webAclArn: waf.attrArn,
    });

    // ---- CloudFront in front of the ALB (§7) --------------------------------
    const distribution = new cloudfront.Distribution(this, "Cdn", {
      defaultBehavior: {
        origin: new origins.LoadBalancerV2Origin(services.alb, {
          // Plain HTTP to a public load balancer: decision 0025 (roadmap E.11).
          protocolPolicy: cloudfront.OriginProtocolPolicy.HTTP_ONLY,
        }),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
        cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED, // app traffic; static assets get their own behaviour later
        originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER,
      },
    });

    // ---- Outputs consumed by the control plane registry ---------------------
    new CfnOutput(this, "PlatformDomain", { value: distribution.distributionDomainName });
    new CfnOutput(this, "UserPoolId", { value: auth.userPool.userPoolId });
    new CfnOutput(this, "UserPoolClientId", { value: auth.userPoolClient.userPoolClientId });
    // The web image's NEXT_PUBLIC_COGNITO_DOMAIN. STATUS.md §20 found it had
    // to be looked up with the AWS CLI after every fresh deploy (§816).
    new CfnOutput(this, "HostedUiDomain", { value: auth.userPoolDomain.baseUrl() });
    new CfnOutput(this, "DataBucketName", { value: data.dataBucket.bucketName });
    new CfnOutput(this, "AccessLogBucketName", { value: data.accessLogBucket.bucketName });
    new CfnOutput(this, "DbSecretArn", { value: data.dbSecret.secretArn });
    new CfnOutput(this, "AppDbSecretArn", { value: data.appDbSecret.secretArn });
    // Teardown (control-plane Deprovisioner) needs the exact physical names
    // of the RETAIN-policy/deletion-protected resources before it deletes
    // the stack - CFN auto-generates all three, so there's nothing to look
    // up once the stack itself is gone. Outputs only; adding these can never
    // trigger a resource replacement.
    new CfnOutput(this, "DatabaseInstanceIdentifier", { value: data.database.instanceIdentifier });
    new CfnOutput(this, "SearchDomainName", { value: data.search.domainName });
    new CfnOutput(this, "ClusterName", { value: services.cluster.clusterName });
    new CfnOutput(this, "AlarmTopicArn", { value: monitoring.topic.topicArn });
    new CfnOutput(this, "ApiServiceName", { value: services.apiService.serviceName });
    new CfnOutput(this, "WorkerServiceName", { value: services.workerService.serviceName });
    new CfnOutput(this, "WebServiceName", { value: services.webService.serviceName });
  }
}

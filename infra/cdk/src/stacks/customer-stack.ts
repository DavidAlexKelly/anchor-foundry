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
import { ServicesConstruct } from "../constructs/services";

export interface CustomerStackProps extends StackProps {
  readonly orgSlug: string;
  readonly platformUrl: string;
  readonly vendorEcrRegistry: string; // e.g. 123456789012.dkr.ecr.eu-west-2.amazonaws.com
  readonly imageTag: string;
  /** See DataStoresConstruct - defaults to true, only ever overridden for
   * throwaway dry-run stacks (app.ts's `deletionProtection` context flag). */
  readonly deletionProtection?: boolean;
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
      dataBucket: data.dataBucket,
      dbSecret: data.dbSecret,
      appDbSecret: data.appDbSecret,
      databaseHost: data.database.instanceEndpoint.hostname,
      databasePort: data.database.instanceEndpoint.port.toString(),
      redisEndpoint: data.redis.attrPrimaryEndPointAddress,
      searchEndpoint: data.search.domainEndpoint,
      userPool: auth.userPool,
      userPoolClientId: auth.userPoolClient.userPoolClientId,
      apiImage: `${props.vendorEcrRegistry}/platform-api`,
      workerImage: `${props.vendorEcrRegistry}/platform-worker`,
      webImage: `${props.vendorEcrRegistry}/platform-web`,
      imageTag: props.imageTag,
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
    data.redisSecurityGroup.addIngressRule(
      services.apiService.connections.securityGroups[0],
      ec2.Port.tcp(6379),
      "api to redis"
    );
    data.redisSecurityGroup.addIngressRule(
      services.workerService.connections.securityGroups[0],
      ec2.Port.tcp(6379),
      "worker to redis"
    );
    data.search.connections.allowFrom(services.apiService, ec2.Port.tcp(443), "api to opensearch");
    data.search.connections.allowFrom(services.workerService, ec2.Port.tcp(443), "worker to opensearch");

    // ---- WAF on the ALB with AWS managed rule sets (§10) --------------------
    const waf = new wafv2.CfnWebACL(this, "Waf", {
      scope: "REGIONAL",
      defaultAction: { allow: {} },
      visibilityConfig: {
        cloudWatchMetricsEnabled: true,
        metricName: "platform-waf",
        sampledRequestsEnabled: true,
      },
      rules: [
        {
          name: "AWSManagedCommonRules",
          priority: 0,
          overrideAction: { none: {} },
          statement: {
            managedRuleGroupStatement: { vendorName: "AWS", name: "AWSManagedRulesCommonRuleSet" },
          },
          visibilityConfig: {
            cloudWatchMetricsEnabled: true,
            metricName: "common-rules",
            sampledRequestsEnabled: true,
          },
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
          visibilityConfig: {
            cloudWatchMetricsEnabled: true,
            metricName: "bad-inputs",
            sampledRequestsEnabled: true,
          },
        },
      ],
    });
    new wafv2.CfnWebACLAssociation(this, "WafAssoc", {
      resourceArn: services.alb.loadBalancerArn,
      webAclArn: waf.attrArn,
    });

    // ---- CloudFront in front of the ALB (§7) --------------------------------
    const distribution = new cloudfront.Distribution(this, "Cdn", {
      defaultBehavior: {
        origin: new origins.LoadBalancerV2Origin(services.alb, {
          protocolPolicy: cloudfront.OriginProtocolPolicy.HTTP_ONLY, // ALB TLS added post-cert issuance
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
    new CfnOutput(this, "ApiServiceName", { value: services.apiService.serviceName });
    new CfnOutput(this, "WorkerServiceName", { value: services.workerService.serviceName });
    new CfnOutput(this, "WebServiceName", { value: services.webService.serviceName });
  }
}

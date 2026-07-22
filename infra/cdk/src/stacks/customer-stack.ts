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
import { ServicesConstruct } from "../constructs/services";

export interface CustomerStackProps extends StackProps {
  readonly orgSlug: string;
  readonly platformUrl: string;
  readonly vendorEcrRegistry: string; // e.g. 123456789012.dkr.ecr.eu-west-2.amazonaws.com
  readonly imageTag: string;
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
    const data = new DataStoresConstruct(this, "Data", { vpc, orgSlug: props.orgSlug });
    Tags.of(data.dataBucket).add("platform:component", "storage");
    Tags.of(data.database).add("platform:component", "database");
    Tags.of(data.search).add("platform:component", "object-search");

    // ---- Auth ---------------------------------------------------------------
    const auth = new AuthConstruct(this, "Auth", {
      orgSlug: props.orgSlug,
      platformUrl: props.platformUrl,
    });

    // ---- Compute ------------------------------------------------------------
    const services = new ServicesConstruct(this, "Services", {
      vpc,
      dataBucket: data.dataBucket,
      dbSecret: data.dbSecret,
      appDbSecret: data.appDbSecret,
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

    // Network paths: only the services may reach the stores.
    data.database.connections.allowFrom(services.apiService, ec2.Port.tcp(5432), "api -> postgres");
    data.database.connections.allowFrom(services.workerService, ec2.Port.tcp(5432), "worker -> postgres");
    data.redisSecurityGroup.addIngressRule(
      services.apiService.connections.securityGroups[0],
      ec2.Port.tcp(6379),
      "api -> redis"
    );
    data.redisSecurityGroup.addIngressRule(
      services.workerService.connections.securityGroups[0],
      ec2.Port.tcp(6379),
      "worker -> redis"
    );
    data.search.connections.allowFrom(services.apiService, ec2.Port.tcp(443), "api -> opensearch");
    data.search.connections.allowFrom(services.workerService, ec2.Port.tcp(443), "worker -> opensearch");

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
    new CfnOutput(this, "DbSecretArn", { value: data.dbSecret.secretArn });
    new CfnOutput(this, "AppDbSecretArn", { value: data.appDbSecret.secretArn });
    new CfnOutput(this, "ClusterName", { value: services.cluster.clusterName });
    new CfnOutput(this, "ApiServiceName", { value: services.apiService.serviceName });
    new CfnOutput(this, "WorkerServiceName", { value: services.workerService.serviceName });
    new CfnOutput(this, "WebServiceName", { value: services.webService.serviceName });
  }
}

import { CfnOutput, Duration, Stack, StackProps, Tags } from "aws-cdk-lib";
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
import { ORIGIN_READ_TIMEOUT_S, ServicesConstruct } from "../constructs/services";
import { webAclRules } from "../constructs/waf";

/** The secret the platform's OIDC signing key is kept in (§871): under the
 * prefix the task roles may manage (`anchor/connections/*`, §846). */
export const OIDC_SIGNING_KEY_SECRET = "anchor/connections/_platform/oidc-signing-key";

/** Where Next serves its content-hashed build output (§865). */
export const STATIC_ASSETS = "/_next/static/*";
/** How long a browser keeps to HTTPS for the platform's host (§920). */
export const HSTS_DAYS = 365;

export interface CustomerStackProps extends StackProps {
  readonly orgSlug: string;
  /** A further address the customer serves the platform at, as
   * `https://host`. Optional: the distribution's own address is always
   * allowed (§849). Nothing in this stack routes a custom domain to the
   * distribution yet (decision 0025, option C), so this is for a domain set
   * up outside it. */
  readonly platformUrl?: string;
  /** Sends invitations through SES from this verified address (§866). */
  readonly inviteFromEmail?: string;
  /** SHA-256 of the provisioner's first-owner token (§886; ServicesProps). */
  readonly bootstrapTokenHash?: string;
  readonly vendorEcrRegistry: string; // e.g. 123456789012.dkr.ecr.eu-west-2.amazonaws.com
  readonly imageTag: string;
  /** See DataStoresConstruct - defaults to true, only ever overridden for
   * throwaway dry-run stacks (app.ts's `deletionProtection` context flag). */
  readonly deletionProtection?: boolean;
  /** Where objects live: "postgres" (the default) or "opensearch", after the
   * cutover in docs/deploying.md (§814; app.ts's `objectStore` context). */
  readonly objectStore?: "postgres" | "opensearch";
  /** How CloudFront reaches the services (decision 0025, §909; app.ts's
   * `originAccess` context). "public" when unset. */
  readonly originAccess?: "public" | "vpc";
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
    // Its sign-in addresses are set below, once the distribution exists.
    const auth = new AuthConstruct(this, "Auth", {
      orgSlug: props.orgSlug,
      inviteFromEmail: props.inviteFromEmail,
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
      bootstrapTokenHash: props.bootstrapTokenHash,
      internalLoadBalancer: props.originAccess === "vpc",
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
    // Decision 0025 (roadmap E.11). "public": plain HTTP to an internet-facing
    // load balancer, which anyone who learns its name can reach directly.
    // "vpc" (option B, §909): the load balancer is internal, and CloudFront
    // reaches it through a VPC origin, inside AWS's network.
    const origin = props.originAccess === "vpc"
      ? origins.VpcOrigin.withApplicationLoadBalancer(services.alb, {
          protocolPolicy: cloudfront.OriginProtocolPolicy.HTTP_ONLY,
          httpPort: 80,
          readTimeout: Duration.seconds(ORIGIN_READ_TIMEOUT_S),
        })
      : new origins.LoadBalancerV2Origin(services.alb, {
          protocolPolicy: cloudfront.OriginProtocolPolicy.HTTP_ONLY,
          // §918: shorter than the load balancer's idle timeout, which is
          // shorter than the servers' keep-alive (constructs/services.ts).
          readTimeout: Duration.seconds(ORIGIN_READ_TIMEOUT_S),
        });
    // **HTTPS from the first request on** (§920). CloudFront redirects plain
    // HTTP, but a redirect is itself sent in plain HTTP, so whoever sits on
    // the network between a person and the platform could answer that first
    // request instead. Strict-Transport-Security tells the browser to make
    // every later request over HTTPS without asking. Set here rather than by
    // the services because CloudFront is the only hop that speaks HTTPS; a
    // year, as the header's own guidance has it, and only for this host - a
    // customer's domain's other names are the customer's to decide.
    const securityHeaders = new cloudfront.ResponseHeadersPolicy(this, "SecurityHeaders", {
      securityHeadersBehavior: {
        strictTransportSecurity: {
          accessControlMaxAge: Duration.days(HSTS_DAYS),
          includeSubdomains: false,
          override: true,
        },
      },
    });
    const distribution = new cloudfront.Distribution(this, "Cdn", {
      defaultBehavior: {
        origin,
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
        cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED, // app traffic: pages and the API
        originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER,
        responseHeadersPolicy: securityHeaders,
      },
      additionalBehaviors: {
        // **The web app's build output, cached at the edge** (§865). Next
        // names every file under /_next/static/ by a hash of its contents
        // and serves it as immutable, so a cached copy can never be stale.
        // Under the default behaviour every page load fetched its JavaScript
        // and CSS through the load balancer from a web task, uncached, on
        // every visit. Nothing a person sees differs, and nothing here is
        // per-user: no cookie, header or query string is forwarded.
        [STATIC_ASSETS]: {
          origin,
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD,
          cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
          compress: true,
          responseHeadersPolicy: securityHeaders,
        },
      },
    });

    // ---- Where the platform is served (§849) ---------------------------------
    // The distribution's own address is the one a viewer reaches, so it is the
    // one the hosted UI must send them back to, and the one the API names when
    // it hands out an address of itself (a listener's endpoint, an outbound
    // application's OAuth callback). The API cannot work it out per request:
    // it hears plain HTTP from the load balancer (decision 0025).
    const servedAt = `https://${distribution.distributionDomainName}`;
    auth.allowAddresses(props.platformUrl ? [servedAt, props.platformUrl] : [servedAt]);
    const api = services.apiService.taskDefinition.defaultContainer!;
    api.addEnvironment("PLATFORM_PUBLIC_URL", servedAt);
    // And where the sign-in page sends a person (§851). The web image is the
    // same for every stack, so it cannot carry this pool's hosted UI; it asks
    // the API (`GET /api/auth/config`), which reads it here.
    api.addEnvironment("COGNITO_DOMAIN", auth.userPoolDomain.baseUrl());
    // The platform as an OpenID Connect provider (§599, §871), so a source can
    // trust the platform instead of holding its credentials. The issuer is
    // where a source fetches the key set, so it is the address a source can
    // reach; the key is one the first API task makes and stores under the
    // prefix both roles may read, since CloudFormation cannot generate one.
    const worker = services.workerService.taskDefinition.defaultContainer!;
    for (const container of [api, worker]) {
      container.addEnvironment("OIDC_ISSUER", `${servedAt}/api/oidc`);
      container.addEnvironment("OIDC_SIGNING_KEY_SECRET", OIDC_SIGNING_KEY_SECRET);
    }

    // ---- Outputs consumed by the control plane registry ---------------------
    new CfnOutput(this, "PlatformUrl", { value: servedAt });
    new CfnOutput(this, "PlatformDomain", { value: distribution.distributionDomainName });
    new CfnOutput(this, "UserPoolId", { value: auth.userPool.userPoolId });
    new CfnOutput(this, "UserPoolClientId", { value: auth.userPoolClient.userPoolClientId });
    // The hosted UI, for an operator. STATUS.md §20 found it had to be looked
    // up with the AWS CLI after every fresh deploy (§816), to rebuild the web
    // image with it; since §851 the API hands it to the page instead.
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

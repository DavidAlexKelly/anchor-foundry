import { Duration, RemovalPolicy } from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as elasticache from "aws-cdk-lib/aws-elasticache";
import * as kms from "aws-cdk-lib/aws-kms";
import * as opensearch from "aws-cdk-lib/aws-opensearchservice";
import * as rds from "aws-cdk-lib/aws-rds";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import { Construct } from "constructs";

export interface DataStoresProps {
  readonly vpc: ec2.IVpc;
  readonly orgSlug: string;
}

/**
 * All stateful stores in the customer account (spec §6 "What Runs Where"),
 * with the §10 "Security Defaults in CDK" applied verbatim:
 *   - S3: KMS encryption, public access blocked, versioning, access logging
 *   - RDS: encrypted, not publicly accessible, deletion protection, backups
 *   - Everything in private VPC subnets
 */
export class DataStoresConstruct extends Construct {
  public readonly dataKey: kms.Key;
  public readonly dataBucket: s3.Bucket;
  public readonly accessLogBucket: s3.Bucket;
  public readonly database: rds.DatabaseInstance;
  public readonly dbSecret: secretsmanager.ISecret;
  /** Separate credential for the RLS-subject application role (db 0006). */
  public readonly appDbSecret: secretsmanager.Secret;
  public readonly redis: elasticache.CfnReplicationGroup;
  public readonly redisSecurityGroup: ec2.SecurityGroup;
  public readonly search: opensearch.Domain;

  constructor(scope: Construct, id: string, props: DataStoresProps) {
    super(scope, id);
    const { vpc } = props;

    this.dataKey = new kms.Key(this, "DataKey", {
      enableKeyRotation: true,
      description: "Platform data encryption key",
      removalPolicy: RemovalPolicy.RETAIN,
    });

    this.accessLogBucket = new s3.Bucket(this, "AccessLogs", {
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
      lifecycleRules: [{ expiration: Duration.days(365) }],
      removalPolicy: RemovalPolicy.RETAIN,
    });

    // §8: single customer data bucket; workspace isolation via IAM prefix
    // conditions applied to task roles (see services.ts).
    this.dataBucket = new s3.Bucket(this, "DataBucket", {
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: this.dataKey,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      versioned: true, // §10: versioning on
      serverAccessLogsBucket: this.accessLogBucket, // §10: access logging
      serverAccessLogsPrefix: "s3-data/",
      removalPolicy: RemovalPolicy.RETAIN,
    });

    const dbSg = new ec2.SecurityGroup(this, "DbSg", { vpc, allowAllOutbound: false });

    this.database = new rds.DatabaseInstance(this, "Postgres", {
      engine: rds.DatabaseInstanceEngine.postgres({
        version: rds.PostgresEngineVersion.VER_16,
      }),
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS }, // §10: private subnets
      instanceType: ec2.InstanceType.of(ec2.InstanceClass.T4G, ec2.InstanceSize.MEDIUM),
      allocatedStorage: 50,
      maxAllocatedStorage: 500,
      storageEncrypted: true, // §10
      storageEncryptionKey: this.dataKey,
      publiclyAccessible: false, // §10
      deletionProtection: true, // §10
      backupRetention: Duration.days(14), // §10: automated backups
      credentials: rds.Credentials.fromGeneratedSecret("platform"),
      databaseName: "platform",
      securityGroups: [dbSg],
      multiAz: false, // single-AZ default at mid-market price point; enterprise plan flips this
      removalPolicy: RemovalPolicy.RETAIN,
    });
    // Generated master secret always exists when using fromGeneratedSecret.
    this.dbSecret = this.database.secret as secretsmanager.ISecret;

    this.appDbSecret = new secretsmanager.Secret(this, "AppDbSecret", {
      description: "platform_app role credentials (RLS-subject application role)",
      generateSecretString: {
        secretStringTemplate: JSON.stringify({ username: "platform_app" }),
        generateStringKey: "password",
        excludeCharacters: "\"'\\/@",
        passwordLength: 40,
      },
    });

    // ElastiCache Redis — Celery queues + API caching (spec §7).
    this.redisSecurityGroup = new ec2.SecurityGroup(this, "RedisSg", {
      vpc,
      allowAllOutbound: false,
    });
    const redisSubnets = new elasticache.CfnSubnetGroup(this, "RedisSubnets", {
      description: "Platform redis subnets",
      subnetIds: vpc.selectSubnets({ subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS }).subnetIds,
    });
    this.redis = new elasticache.CfnReplicationGroup(this, "Redis", {
      replicationGroupDescription: "Platform cache and job queue",
      engine: "redis",
      cacheNodeType: "cache.t4g.small",
      numCacheClusters: 1,
      atRestEncryptionEnabled: true,
      transitEncryptionEnabled: true,
      automaticFailoverEnabled: false,
      cacheSubnetGroupName: redisSubnets.ref,
      securityGroupIds: [this.redisSecurityGroup.securityGroupId],
    });
    this.redis.addDependency(redisSubnets);

    // OpenSearch — object instance search and aggregation (spec §7, §8).
    this.search = new opensearch.Domain(this, "Search", {
      version: opensearch.EngineVersion.OPENSEARCH_2_11,
      vpc,
      vpcSubnets: [{ subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS, availabilityZones: [vpc.availabilityZones[0]] }],
      capacity: { dataNodes: 1, dataNodeInstanceType: "t3.small.search", multiAzWithStandbyEnabled: false },
      ebs: { volumeSize: 30 },
      encryptionAtRest: { enabled: true },
      nodeToNodeEncryption: true,
      enforceHttps: true,
      // §4: document-level security per workspace configured at runtime by
      // the API via fine-grained access control roles.
      fineGrainedAccessControl: { masterUserName: "platform-admin" },
      zoneAwareness: { enabled: false },
      removalPolicy: RemovalPolicy.RETAIN,
    });
  }
}

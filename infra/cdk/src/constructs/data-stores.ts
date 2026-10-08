import { Duration, RemovalPolicy } from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as iam from "aws-cdk-lib/aws-iam";
import * as kms from "aws-cdk-lib/aws-kms";
import * as opensearch from "aws-cdk-lib/aws-opensearchservice";
import * as rds from "aws-cdk-lib/aws-rds";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import { Construct } from "constructs";

/** The database's automated backups (§10). */
export const BACKUP_DAYS = 14;
/** How long the data bucket keeps a deleted or replaced file (§852): the
 * backup window, plus two weeks to notice and carry out a restore. */
export const NONCURRENT_VERSION_DAYS = 30;

export interface DataStoresProps {
  readonly vpc: ec2.IVpc;
  readonly orgSlug: string;
  /** Defaults to true (spec §10: a bad deploy can't wipe a customer's
   * database). Only ever overridden false for throwaway dry-run stacks
   * that expect to be torn down repeatedly - see app.ts's
   * `deletionProtection` context flag. Without it, ANY failed CREATE that
   * gets as far as this resource forces a manual RDS teardown before the
   * automatic rollback can finish, because CloudFormation checks this
   * template property (not the live value) before deleting the instance -
   * true even during its own rollback, not just a deliberate delete-stack. */
  readonly deletionProtection?: boolean;
  /** Objects live in the OpenSearch domain rather than Postgres (§814). Off
   * unless the stack asks: turning it on for a stack whose objects are still
   * in Postgres would point the API at an empty index, so it follows the
   * cutover (`docs/deploying.md`) rather than arriving with a deploy. */
  readonly objectIndex?: boolean;
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
  public readonly search: opensearch.Domain;
  /** The domain's master user, `{"username", "password"}`, which is what the
   * API's and the worker's `OPENSEARCH_SECRET_ARN` names (§814). */
  public readonly searchMasterSecret: secretsmanager.ISecret;

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
      // **How long a deleted or replaced file can still be recovered (§852).**
      // Versioning with no rule kept every previous version forever: a
      // deleted dataset was billed, and held, for the life of the stack, and
      // "delete" never meant gone. A previous version now lasts
      // NONCURRENT_VERSION_DAYS, longer than the database's backups, because
      // the restore runbook (docs/deploying.md) repairs a file deleted since
      // the restore point from its previous version - a database restored to
      // its oldest backup must still find those. stack-check.ts holds the two
      // together. An upload abandoned part-way is cleared after a week.
      lifecycleRules: [{
        noncurrentVersionExpiration: Duration.days(NONCURRENT_VERSION_DAYS),
        abortIncompleteMultipartUploadAfter: Duration.days(7),
        expiredObjectDeleteMarker: true,
      }],
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
      deletionProtection: props.deletionProtection ?? true, // §10
      backupRetention: Duration.days(BACKUP_DAYS), // §10: automated backups
      // §930: which statements the database spends its time on. Nothing on a
      // stack logged a slow query or kept a statement's timings, so a slow
      // page was a guess about which query. CloudWatch Database Insights'
      // Standard mode, which is Performance Insights' free seven days; its
      // samples are encrypted with the same key as the data they quote.
      enablePerformanceInsights: true,
      databaseInsightsMode: rds.DatabaseInsightsMode.STANDARD,
      performanceInsightRetention: rds.PerformanceInsightRetention.DEFAULT,
      performanceInsightEncryptionKey: this.dataKey,
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

    // No Redis (§845, decision 0026). Spec §7 put an ElastiCache node here
    // for Celery queues and API caching; the worker runs on Dagster and the
    // API caches nothing in Redis, so the node was billed in every stack and
    // read by nothing. Re-add it with the first thing that uses it.

    // OpenSearch - object instance search and aggregation (spec §7, §8).
    this.search = new opensearch.Domain(this, "Search", {
      version: opensearch.EngineVersion.OPENSEARCH_2_11,
      vpc,
      vpcSubnets: [{ subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS, availabilityZones: [vpc.availabilityZones[0]] }],
      capacity: { dataNodes: 1, dataNodeInstanceType: "t3.small.search", multiAzWithStandbyEnabled: false },
      ebs: { volumeSize: 30 },
      encryptionAtRest: { enabled: true },
      nodeToNodeEncryption: true,
      enforceHttps: true,
      // Explicit, not left to the library default: AWS now rejects new
      // domain creation requesting the older Policy-Min-TLS-1-0-2019-07
      // policy outright, and older aws-cdk-lib versions still default to it.
      tlsSecurityPolicy: opensearch.TLSSecurityPolicy.TLS_1_2,
      // §4: document-level security per workspace configured at runtime by
      // the API via fine-grained access control roles.
      fineGrainedAccessControl: { masterUserName: "platform-admin" },
      zoneAwareness: { enabled: false },
      removalPolicy: RemovalPolicy.RETAIN,
    });
    // Generated by the domain construct itself when a master user name is
    // given without a password, as a secret holding `{username, password}` -
    // the shape `gateway_from_env` reads. It is not a public property, hence
    // the lookup; a CDK upgrade that renamed it fails here, at synth.
    this.searchMasterSecret = this.search.node.findChild("MasterUser") as secretsmanager.ISecret;
    if (props.objectIndex) {
      // Fine-grained access control decides who may do what, with the master
      // user's basic auth, so the domain's own policy lets requests through
      // to it - AWS's documented pairing, and what CDK's `useUnsignedBasicAuth`
      // writes. Without it the domain refuses every unsigned request before
      // fine-grained access control sees one. Reaching the domain at all is
      // still only possible from the API's and worker's security groups.
      this.search.addAccessPolicies(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ["es:ESHttp*"],
          principals: [new iam.AnyPrincipal()],
          resources: [`${this.search.domainArn}/*`],
        })
      );
    }
  }
}

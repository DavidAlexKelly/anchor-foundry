import * as path from "path";
import { Duration } from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as rds from "aws-cdk-lib/aws-rds";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as triggers from "aws-cdk-lib/triggers";
import { Construct } from "constructs";

export interface MigrationTriggerProps {
  readonly vpc: ec2.IVpc;
  readonly database: rds.IDatabaseInstance;
  /** Master credentials (DDL owner - applies the migration files). */
  readonly dbSecret: secretsmanager.ISecret;
  /** platform_app credentials - only its password is read, to sync migration
   * 0006's placeholder to the real generated value (STATUS.md §17 item 9). */
  readonly appDbSecret: secretsmanager.ISecret;
}

const DB_PACKAGE_DIR = path.join(__dirname, "..", "..", "..", "..", "packages", "db");

/**
 * Runs packages/db's migrations against the customer's RDS instance on
 * every deploy (spec §6 "Runs any database migrations automatically").
 * Previously a manual step: STATUS.md §17 documents running migrate.py by
 * hand via a CloudShell VPC session on every real deploy, because nothing
 * in the pipeline ever did this - Provisioner._deploy's own docstring
 * already promised it, the automation just didn't exist yet.
 *
 * `triggers.TriggerFunction` (not an ECS one-off task) because CDK expresses
 * "runs once per deploy, before X and after Y" directly as executeAfter/
 * executeBefore construct dependencies - customer-stack.ts orders this
 * after the database and before the ECS services that need its schema.
 */
export class MigrationTriggerConstruct extends Construct {
  public readonly trigger: triggers.TriggerFunction;

  constructor(scope: Construct, id: string, props: MigrationTriggerProps) {
    super(scope, id);
    const { vpc, database, dbSecret, appDbSecret } = props;

    this.trigger = new triggers.TriggerFunction(this, "Fn", {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: "lambda_handler.handler",
      timeout: Duration.minutes(5),
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      code: lambda.Code.fromAsset(DB_PACKAGE_DIR, {
        bundling: {
          // Docker only, deliberately - no `local` fallback. CDK tries
          // `local.tryBundle()` first UNCONDITIONALLY, regardless of
          // whether Docker is available, falling back to Docker only if it
          // returns false/throws - it is not "Docker if available, else
          // local". A `local` fallback here that runs the *host's* pip with
          // `--platform manylinux2014_x86_64 --only-binary=:all:` (added
          // once, to let `cdk synth` run in a Docker-less dev sandbox)
          // silently WON on a real deploy from a Mac that had Docker
          // running the whole time, producing a psycopg_binary wheel that
          // imported fine locally but failed at Lambda runtime ("no pq
          // wrapper available" - none of psycopg's c/binary/python
          // implementations actually worked). Native-extension deps like
          // psycopg need the exact Amazon Linux build environment the
          // official bundling image provides; there is no safe host-pip
          // substitute for that, so this only ever bundles via Docker now -
          // `cdk synth`/`cdk deploy` for this stack requires a running
          // Docker daemon, same as this repo's own Dockerfile-based service
          // images already do.
          image: lambda.Runtime.PYTHON_3_12.bundlingImage,
          command: [
            "bash",
            "-c",
            "pip install -r requirements.txt -t /asset-output && " +
              "cp migrate.py lambda_handler.py /asset-output && " +
              "cp -r migrations /asset-output",
          ],
        },
      }),
      environment: {
        DB_SECRET_ARN: dbSecret.secretArn,
        APP_DB_SECRET_ARN: appDbSecret.secretArn,
        DATABASE_HOST: database.instanceEndpoint.hostname,
        DATABASE_PORT: database.instanceEndpoint.port.toString(),
        DATABASE_NAME: "platform",
      },
      executeAfter: [database],
    });

    dbSecret.grantRead(this.trigger);
    appDbSecret.grantRead(this.trigger);
    database.connections.allowFrom(this.trigger, ec2.Port.tcp(5432), "migration lambda to postgres");
  }
}

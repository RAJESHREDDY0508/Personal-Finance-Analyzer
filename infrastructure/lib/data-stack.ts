/**
 * Data Stack — RDS PostgreSQL, SQS queues, S3 buckets.
 *
 * Replaced MSK Kafka with Amazon SQS. SQS is serverless, deploys in seconds,
 * requires no broker sizing, and costs fractions of a cent per message.
 * Each former Kafka topic becomes an SQS queue with a companion DLQ.
 *
 * Queue URLs are stored in SSM Parameter Store so the EC2 instances can read
 * them at startup without hard-coding account IDs.
 */
import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as rds from "aws-cdk-lib/aws-rds";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as sqs from "aws-cdk-lib/aws-sqs";
import * as ssm from "aws-cdk-lib/aws-ssm";
import { Construct } from "constructs";

interface DataStackProps extends cdk.StackProps {
  stage: string;
  vpc: ec2.Vpc;
  dbSecurityGroup: ec2.SecurityGroup;
  /** Kept for interface compatibility with bin/infrastructure.ts — not used. */
  kafkaSecurityGroup: ec2.SecurityGroup;
}

/** All SQS queues created by this stack, keyed by logical name. */
export interface PfaQueues {
  statementUploaded: sqs.Queue;
  statementParsed: sqs.Queue;
  transactionsCategorized: sqs.Queue;
  anomaliesDetected: sqs.Queue;
  reportSchedule: sqs.Queue;
  reportGenerated: sqs.Queue;
  subscriptionEvents: sqs.Queue;
}

export class PfaDataStack extends cdk.Stack {
  public readonly dbSecret: secretsmanager.Secret;
  public readonly statementsBucket: s3.Bucket;
  public readonly reportsBucket: s3.Bucket;
  public readonly artifactsBucket: s3.Bucket;
  public readonly queues: PfaQueues;

  constructor(scope: Construct, id: string, props: DataStackProps) {
    super(scope, id, props);

    const { stage, vpc, dbSecurityGroup } = props;
    const isProd = stage === "prod";

    // ── RDS PostgreSQL ───────────────────────────────────────
    this.dbSecret = new secretsmanager.Secret(this, "DbSecret", {
      secretName: `pfa/db/${stage}`,
      generateSecretString: {
        secretStringTemplate: JSON.stringify({ username: "pfa_user" }),
        generateStringKey: "password",
        excludePunctuation: true,
        includeSpace: false,
      },
    });

    new rds.DatabaseInstance(this, "PfaDatabase", {
      engine: rds.DatabaseInstanceEngine.postgres({
        version: rds.PostgresEngineVersion.VER_16,
      }),
      instanceType: ec2.InstanceType.of(
        ec2.InstanceClass.T3,
        isProd ? ec2.InstanceSize.LARGE : ec2.InstanceSize.MEDIUM
      ),
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [dbSecurityGroup],
      credentials: rds.Credentials.fromSecret(this.dbSecret),
      databaseName: "pfa_db",
      multiAz: isProd,
      storageEncrypted: true,
      deletionProtection: isProd,
      backupRetention: cdk.Duration.days(isProd ? 7 : 1),
      instanceIdentifier: `pfa-db-${stage}`,
      cloudwatchLogsExports: ["postgresql"],
      // DESTROY skips the final snapshot on deletion — prevents rollback failures
      // when CloudFormation tries to snapshot an instance still in "creating" state.
      removalPolicy: isProd ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
    });

    // ── SQS Queues (replaced MSK Kafka) ──────────────────────
    // Helper: create a queue + companion dead-letter queue.
    const makeQueue = (
      logicalId: string,
      queueName: string,
      visibilityTimeoutSecs: number
    ): sqs.Queue => {
      const dlq = new sqs.Queue(this, `${logicalId}Dlq`, {
        queueName: `pfa-dlq-${queueName}-${stage}`,
        retentionPeriod: cdk.Duration.days(14),
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      });

      return new sqs.Queue(this, logicalId, {
        queueName: `pfa-${queueName}-${stage}`,
        visibilityTimeout: cdk.Duration.seconds(visibilityTimeoutSecs),
        retentionPeriod: cdk.Duration.days(4),
        deadLetterQueue: { queue: dlq, maxReceiveCount: 3 },
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      });
    };

    this.queues = {
      // statement.uploaded → parser worker (allow 5 min to parse + insert)
      statementUploaded: makeQueue("StatementUploadedQueue", "statement-uploaded", 300),
      // statement.parsed → AI categorizer (allow 10 min for GPT batches)
      statementParsed: makeQueue("StatementParsedQueue", "statement-parsed", 600),
      // transactions.categorized → anomaly detector + ML predictor
      transactionsCategorized: makeQueue("TransactionsCategorizedQueue", "transactions-categorized", 300),
      // anomalies.detected → suggestion engine
      anomaliesDetected: makeQueue("AnomaliesDetectedQueue", "anomalies-detected", 120),
      // report.schedule → report generator
      reportSchedule: makeQueue("ReportScheduleQueue", "report-schedule", 300),
      // report.generated → email sender
      reportGenerated: makeQueue("ReportGeneratedQueue", "report-generated", 120),
      // subscription.events → subscription handler
      subscriptionEvents: makeQueue("SubscriptionEventsQueue", "subscription-events", 60),
    };

    // Store queue URLs in SSM so EC2 instances can read them at startup.
    // The EC2 IAM role in app-stack.ts grants read access to /pfa/{stage}/*.
    const queueSsmEntries: Array<[string, string, sqs.Queue]> = [
      ["SsmStatementUploadedUrl",       "statement-uploaded-url",       this.queues.statementUploaded],
      ["SsmStatementParsedUrl",         "statement-parsed-url",         this.queues.statementParsed],
      ["SsmTransactionsCategorizedUrl", "transactions-categorized-url", this.queues.transactionsCategorized],
      ["SsmAnomaliesDetectedUrl",       "anomalies-detected-url",       this.queues.anomaliesDetected],
      ["SsmReportScheduleUrl",          "report-schedule-url",          this.queues.reportSchedule],
      ["SsmReportGeneratedUrl",         "report-generated-url",         this.queues.reportGenerated],
      ["SsmSubscriptionEventsUrl",      "subscription-events-url",      this.queues.subscriptionEvents],
    ];

    for (const [ssmId, paramSuffix, queue] of queueSsmEntries) {
      new ssm.StringParameter(this, ssmId, {
        parameterName: `/pfa/${stage}/sqs/${paramSuffix}`,
        stringValue: queue.queueUrl,
        description: `SQS queue URL for ${paramSuffix}`,
      });
    }

    // ── S3 Buckets ───────────────────────────────────────────
    this.statementsBucket = new s3.Bucket(this, "StatementsBucket", {
      bucketName: `pfa-statements-${stage}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      versioned: false,
      lifecycleRules: [
        { expiration: cdk.Duration.days(365), id: "ExpireOldStatements" },
      ],
      cors: [
        {
          allowedMethods: [s3.HttpMethods.PUT],
          allowedOrigins: ["*"],
          allowedHeaders: ["*"],
          maxAge: 3000,
        },
      ],
      removalPolicy: isProd ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
    });

    this.reportsBucket = new s3.Bucket(this, "ReportsBucket", {
      bucketName: `pfa-reports-${stage}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      removalPolicy: isProd ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
    });

    // NOTE: frontendBucket lives in PfaAppStack (co-located with the CloudFront
    // distribution) to avoid a cyclic cross-stack dependency on the distribution ID.

    // Versioned bucket for CodeDeploy deployment packages uploaded by CI
    this.artifactsBucket = new s3.Bucket(this, "ArtifactsBucket", {
      bucketName: `pfa-artifacts-${stage}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      versioned: true,
      lifecycleRules: [
        {
          id: "ExpireOldArtifacts",
          noncurrentVersionExpiration: cdk.Duration.days(30),
        },
      ],
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ── Outputs ─────────────────────────────────────────────
    new cdk.CfnOutput(this, "DbSecretArn", { value: this.dbSecret.secretArn });
    new cdk.CfnOutput(this, "StatementsBucketName", {
      value: this.statementsBucket.bucketName,
    });
    new cdk.CfnOutput(this, "ReportsBucketName", {
      value: this.reportsBucket.bucketName,
    });
    new cdk.CfnOutput(this, "ArtifactsBucketName", {
      value: this.artifactsBucket.bucketName,
    });

    // Queue URL outputs for quick reference after deploy
    new cdk.CfnOutput(this, "SqsStatementUploadedUrl", {
      value: this.queues.statementUploaded.queueUrl,
      description: "SQS queue for statement.uploaded events",
    });
    new cdk.CfnOutput(this, "SqsStatementParsedUrl", {
      value: this.queues.statementParsed.queueUrl,
    });
    new cdk.CfnOutput(this, "SqsTransactionsCategorizedUrl", {
      value: this.queues.transactionsCategorized.queueUrl,
    });
    new cdk.CfnOutput(this, "SqsAnomaliesDetectedUrl", {
      value: this.queues.anomaliesDetected.queueUrl,
    });
    new cdk.CfnOutput(this, "SqsReportScheduleUrl", {
      value: this.queues.reportSchedule.queueUrl,
    });
    new cdk.CfnOutput(this, "SqsReportGeneratedUrl", {
      value: this.queues.reportGenerated.queueUrl,
    });
    new cdk.CfnOutput(this, "SqsSubscriptionEventsUrl", {
      value: this.queues.subscriptionEvents.queueUrl,
    });
  }
}

/**
 * Data Stack — RDS PostgreSQL, MSK Kafka, S3 buckets.
 */
import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as msk from "aws-cdk-lib/aws-msk";
import * as rds from "aws-cdk-lib/aws-rds";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import { Construct } from "constructs";

interface DataStackProps extends cdk.StackProps {
  stage: string;
  vpc: ec2.Vpc;
  dbSecurityGroup: ec2.SecurityGroup;
  kafkaSecurityGroup: ec2.SecurityGroup;
}

export class PfaDataStack extends cdk.Stack {
  public readonly dbSecret: secretsmanager.Secret;
  public readonly statementsBucket: s3.Bucket;
  public readonly reportsBucket: s3.Bucket;
  public readonly artifactsBucket: s3.Bucket;
  /** Resolves to the MSK TLS bootstrap broker string at deploy time. */
  public readonly kafkaBootstrapServers: string;

  constructor(scope: Construct, id: string, props: DataStackProps) {
    super(scope, id, props);

    const { stage, vpc, dbSecurityGroup, kafkaSecurityGroup } = props;
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
    });

    // ── MSK Kafka ─────────────────────────────────────────────
    // NOTE: MSK costs ~$0.21/hr per m5.large broker. For local development,
    // use docker-compose Kafka and set KAFKA_BOOTSTRAP_SERVERS=localhost:9092.
    const privateSubnetIds = vpc
      .selectSubnets({ subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS })
      .subnetIds;

    const kafkaCluster = new msk.CfnCluster(this, "PfaKafka", {
      clusterName: `pfa-kafka-${stage}`,
      kafkaVersion: "3.6.0",
      // prod = 2 brokers (multi-AZ), dev = 1 broker (single-AZ)
      numberOfBrokerNodes: isProd ? 2 : 1,
      brokerNodeGroupInfo: {
        instanceType: "kafka.m5.large",
        clientSubnets: isProd
          ? privateSubnetIds.slice(0, 2)
          : [privateSubnetIds[0]],
        securityGroups: [kafkaSecurityGroup.securityGroupId],
        storageInfo: {
          ebsStorageInfo: { volumeSize: isProd ? 100 : 20 },
        },
      },
      encryptionInfo: {
        encryptionInTransit: {
          clientBroker: "TLS_PLAINTEXT",
          inCluster: true,
        },
      },
      loggingInfo: {
        brokerLogs: {
          cloudWatchLogs: {
            enabled: true,
            logGroup: `/pfa/${stage}/kafka`,
          },
        },
      },
    });

    // attrBootstrapBrokersTls is a CloudFormation return value; use Fn.getAtt for compatibility
    this.kafkaBootstrapServers = cdk.Fn.getAtt(kafkaCluster.logicalId, "BootstrapBrokersTls").toString();

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
    new cdk.CfnOutput(this, "KafkaBootstrapServers", {
      value: this.kafkaBootstrapServers,
    });
  }
}

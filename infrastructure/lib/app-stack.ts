/**
 * App Stack — EC2 Auto Scaling Group, ALB, CloudFront, CodeDeploy, CloudWatch.
 *
 * Architecture:
 *   Internet → CloudFront → (S3 for /*, ALB for /api/*)
 *   ALB → EC2 Auto Scaling Group (FastAPI on port 8000, private subnets)
 *   CodeDeploy → deploys backend zip from S3 artifacts bucket
 *
 * Optional custom domain:
 *   Pass --context domainName=app.example.com to enable ACM + Route 53.
 *   Without it, the CloudFront *.cloudfront.net domain is used.
 */
import * as cdk from "aws-cdk-lib";
import * as autoscaling from "aws-cdk-lib/aws-autoscaling";
import * as acm from "aws-cdk-lib/aws-certificatemanager";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
import * as cw_actions from "aws-cdk-lib/aws-cloudwatch-actions";
import * as codedeploy from "aws-cdk-lib/aws-codedeploy";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as iam from "aws-cdk-lib/aws-iam";
import * as logs from "aws-cdk-lib/aws-logs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as sns from "aws-cdk-lib/aws-sns";
import * as sns_subs from "aws-cdk-lib/aws-sns-subscriptions";
import { Construct } from "constructs";

interface AppStackProps extends cdk.StackProps {
  stage: string;
  vpc: ec2.Vpc;
  appSecurityGroup: ec2.SecurityGroup;
  albSecurityGroup: ec2.SecurityGroup;
  dbSecret: secretsmanager.Secret;
  statementsBucket: s3.Bucket;
  reportsBucket: s3.Bucket;
  artifactsBucket: s3.Bucket;
}

export class PfaAppStack extends cdk.Stack {
  public readonly albDnsName: string;
  public readonly distributionDomainName: string;

  constructor(scope: Construct, id: string, props: AppStackProps) {
    super(scope, id, props);

    const {
      stage,
      vpc,
      appSecurityGroup,
      albSecurityGroup,
      dbSecret,
      statementsBucket,
      reportsBucket,
      artifactsBucket,
    } = props;

    const isProd = stage === "prod";
    const domainName = this.node.tryGetContext("domainName") as string | undefined;
    const alarmEmail = this.node.tryGetContext("alarmEmail") as string | undefined;

    // ── CloudWatch Log Group ──────────────────────────────────
    const appLogGroup = new logs.LogGroup(this, "AppLogGroup", {
      logGroupName: `/pfa/${stage}/api`,
      retention: isProd ? logs.RetentionDays.THREE_MONTHS : logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ── SNS Alarm Topic ───────────────────────────────────────
    const alarmTopic = new sns.Topic(this, "AlarmTopic", {
      topicName: `pfa-alarms-${stage}`,
      displayName: `PFA ${stage.toUpperCase()} Alarms`,
    });
    if (alarmEmail) {
      alarmTopic.addSubscription(new sns_subs.EmailSubscription(alarmEmail));
    }

    // ── Frontend S3 Bucket ───────────────────────────────────
    // Co-located with CloudFront in this stack to avoid a cyclic cross-stack
    // dependency: OAC bucket policies reference the distribution ID, so the
    // bucket and distribution must be in the same stack.
    const frontendBucket = new s3.Bucket(this, "FrontendBucket", {
      bucketName: `pfa-frontend-${stage}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ── IAM Role for EC2 ─────────────────────────────────────
    const ec2Role = new iam.Role(this, "AppRole", {
      roleName: `pfa-app-role-${stage}`,
      assumedBy: new iam.ServicePrincipal("ec2.amazonaws.com"),
      managedPolicies: [
        // SSM Session Manager access (secure shell without bastion)
        iam.ManagedPolicy.fromAwsManagedPolicyName("AmazonSSMManagedInstanceCore"),
        // CloudWatch agent metrics + logs
        iam.ManagedPolicy.fromAwsManagedPolicyName("CloudWatchAgentServerPolicy"),
      ],
    });

    // S3 access
    statementsBucket.grantReadWrite(ec2Role);
    reportsBucket.grantReadWrite(ec2Role);
    artifactsBucket.grantRead(ec2Role);

    // Secrets Manager — read DB credentials
    dbSecret.grantRead(ec2Role);

    // SSM Parameter Store — read app config
    ec2Role.addToPolicy(
      new iam.PolicyStatement({
        actions: ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"],
        resources: [`arn:aws:ssm:*:*:parameter/pfa/${stage}/*`],
      })
    );

    // SES — send emails
    ec2Role.addToPolicy(
      new iam.PolicyStatement({
        actions: ["ses:SendEmail", "ses:SendRawEmail"],
        resources: ["*"],
      })
    );

    // CloudWatch Logs
    ec2Role.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogStreams",
        ],
        resources: [appLogGroup.logGroupArn],
      })
    );

    // CodeDeploy — allow EC2 to report deployment status
    ec2Role.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          "codedeploy:PutLifecycleEventHookExecutionStatus",
        ],
        resources: ["*"],
      })
    );

    // SQS — workers send/receive/delete messages on all PFA queues
    ec2Role.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          "sqs:SendMessage",
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:GetQueueUrl",
          "sqs:ChangeMessageVisibility",
        ],
        resources: [`arn:aws:sqs:*:*:pfa-*-${stage}`],
      })
    );

    // ── EC2 User Data ─────────────────────────────────────────
    // Runs once at instance launch. Installs dependencies and the
    // CodeDeploy agent (which handles subsequent app deployments).
    const userData = ec2.UserData.forLinux();
    userData.addCommands(
      "set -euxo pipefail",
      "exec > >(tee /var/log/userdata.log) 2>&1",
      "",
      "# ── System update & base packages ──────────────────────",
      "dnf update -y",
      "dnf install -y python3.12 python3.12-pip python3.12-devel",
      "dnf install -y gcc git ruby wget jq",
      "",
      "# ── CodeDeploy agent ─────────────────────────────────────",
      `REGION=$(curl -s http://169.254.169.254/latest/meta-data/placement/region)`,
      "cd /tmp",
      `wget -q "https://aws-codedeploy-\${REGION}.s3.\${REGION}.amazonaws.com/latest/install"`,
      "chmod +x ./install",
      "./install auto",
      "systemctl enable codedeploy-agent",
      "systemctl start codedeploy-agent",
      "",
      "# ── CloudWatch agent ─────────────────────────────────────",
      "dnf install -y amazon-cloudwatch-agent",
      "",
      "# ── Application user & directories ──────────────────────",
      "id -u pfa &>/dev/null || useradd -r -s /sbin/nologin -d /opt/pfa pfa",
      "mkdir -p /opt/pfa /etc/pfa",
      "chown pfa:pfa /opt/pfa",
      "chmod 750 /etc/pfa",
      "",
      "echo 'UserData bootstrap complete — awaiting CodeDeploy deployment'"
    );

    // ── Launch Template ───────────────────────────────────────
    const launchTemplate = new ec2.LaunchTemplate(this, "AppLaunchTemplate", {
      launchTemplateName: `pfa-app-lt-${stage}`,
      machineImage: ec2.MachineImage.latestAmazonLinux2023(),
      instanceType: ec2.InstanceType.of(
        ec2.InstanceClass.T3,
        isProd ? ec2.InstanceSize.LARGE : ec2.InstanceSize.MEDIUM
      ),
      securityGroup: appSecurityGroup,
      role: ec2Role,
      userData,
      blockDevices: [
        {
          deviceName: "/dev/xvda",
          volume: ec2.BlockDeviceVolume.ebs(20, {
            encrypted: true,
            deleteOnTermination: true,
          }),
        },
      ],
    });

    // ── Auto Scaling Group ────────────────────────────────────
    const asg = new autoscaling.AutoScalingGroup(this, "AppAsg", {
      autoScalingGroupName: `pfa-asg-${stage}`,
      vpc,
      launchTemplate,
      minCapacity: 1,
      maxCapacity: isProd ? 4 : 2,
      // desiredCapacity omitted intentionally — setting it would reset the ASG size
      // on every CDK deployment, overriding auto-scaling decisions. CDK will use
      // minCapacity (1) as the initial desired count on first deploy.
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      healthChecks: autoscaling.HealthChecks.withAdditionalChecks({
        additionalTypes: [autoscaling.AdditionalHealthCheckType.ELB],
        gracePeriod: cdk.Duration.seconds(90),
      }),
      cooldown: cdk.Duration.seconds(300),
    });

    // CPU-based auto-scaling
    asg.scaleOnCpuUtilization("CpuScaling", {
      targetUtilizationPercent: 70,
      cooldown: cdk.Duration.seconds(300),
    });

    // ── Application Load Balancer ─────────────────────────────
    const alb = new elbv2.ApplicationLoadBalancer(this, "AppAlb", {
      vpc,
      internetFacing: true,
      securityGroup: albSecurityGroup,
      loadBalancerName: `pfa-alb-${stage}`,
    });
    this.albDnsName = alb.loadBalancerDnsName;

    // Target group — FastAPI on port 8000
    const targetGroup = new elbv2.ApplicationTargetGroup(this, "AppTargetGroup", {
      targetGroupName: `pfa-tg-${stage}`,
      vpc,
      port: 8000,
      protocol: elbv2.ApplicationProtocol.HTTP,
      targets: [asg],
      healthCheck: {
        path: "/health",
        interval: cdk.Duration.seconds(30),
        healthyThresholdCount: 2,
        unhealthyThresholdCount: 3,
        timeout: cdk.Duration.seconds(10),
      },
      deregistrationDelay: cdk.Duration.seconds(30),
    });

    // HTTP → HTTPS redirect
    alb.addListener("HttpListener", {
      port: 80,
      defaultAction: elbv2.ListenerAction.redirect({
        port: "443",
        protocol: "HTTPS",
        permanent: true,
      }),
    });

    // HTTPS listener — requires ACM cert (custom domain) or HTTP-only dev mode
    let httpsListener: elbv2.ApplicationListener | undefined;
    let cert: acm.Certificate | undefined;

    if (domainName) {
      cert = new acm.Certificate(this, "ApiCert", {
        domainName: `api.${domainName}`,
        validation: acm.CertificateValidation.fromDns(),
      });

      httpsListener = alb.addListener("HttpsListener", {
        port: 443,
        certificates: [cert],
        defaultAction: elbv2.ListenerAction.forward([targetGroup]),
        sslPolicy: elbv2.SslPolicy.RECOMMENDED_TLS,
      });
    } else {
      // Dev fallback: plain HTTP listener (CloudFront terminates TLS)
      alb.addListener("HttpDevListener", {
        port: 8080,
        defaultAction: elbv2.ListenerAction.forward([targetGroup]),
      });
    }

    // Keep TS happy — suppress unused-variable warnings
    void httpsListener;

    // ── CloudFront Distribution (optional) ───────────────────
    // Skip CloudFront when --context skipCloudFront=true is passed.
    // New AWS accounts sometimes need account verification before CloudFront
    // can be used.  In that case deploy with skipCloudFront=true and access
    // the app directly via the ALB DNS name on port 8080.
    // Once your account is verified, redeploy without the flag to add CloudFront.
    const skipCloudFront =
      (this.node.tryGetContext("skipCloudFront") as string | undefined) === "true";

    if (!skipCloudFront) {
      const frontendOac = new cloudfront.S3OriginAccessControl(this, "FrontendOac", {
        description: `PFA frontend OAC - ${stage}`,
      });

      const apiOriginPort = domainName ? 443 : 8080;
      const apiOriginProtocol = domainName
        ? cloudfront.OriginProtocolPolicy.HTTPS_ONLY
        : cloudfront.OriginProtocolPolicy.HTTP_ONLY;

      const albOrigin = new origins.LoadBalancerV2Origin(alb, {
        protocolPolicy: apiOriginProtocol,
        httpPort: apiOriginPort,
        httpsPort: 443,
        readTimeout: cdk.Duration.seconds(60),
      });

      const distribution = new cloudfront.Distribution(this, "PfaDistribution", {
        comment: `PFA ${stage} distribution`,
        defaultBehavior: {
          origin: origins.S3BucketOrigin.withOriginAccessControl(frontendBucket, {
            originAccessControl: frontendOac,
          }),
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
          compress: true,
        },
        additionalBehaviors: {
          "/api/*": {
            origin: albOrigin,
            viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
            cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
            originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER,
          },
        },
        errorResponses: [
          {
            httpStatus: 403,
            responseHttpStatus: 200,
            responsePagePath: "/index.html",
            ttl: cdk.Duration.seconds(0),
          },
          {
            httpStatus: 404,
            responseHttpStatus: 200,
            responsePagePath: "/index.html",
            ttl: cdk.Duration.seconds(0),
          },
        ],
        ...(domainName && cert
          ? {
              domainNames: [domainName, `www.${domainName}`],
              certificate: new acm.Certificate(this, "CfCert", {
                domainName,
                subjectAlternativeNames: [`www.${domainName}`],
                validation: acm.CertificateValidation.fromDns(),
              }),
            }
          : {}),
        priceClass: isProd
          ? cloudfront.PriceClass.PRICE_CLASS_ALL
          : cloudfront.PriceClass.PRICE_CLASS_100,
      });
      this.distributionDomainName = distribution.distributionDomainName;

      frontendBucket.addToResourcePolicy(
        new iam.PolicyStatement({
          principals: [new iam.ServicePrincipal("cloudfront.amazonaws.com")],
          actions: ["s3:GetObject"],
          resources: [frontendBucket.arnForObjects("*")],
          conditions: {
            StringEquals: {
              "AWS:SourceArn": `arn:${this.partition}:cloudfront::${this.account}:distribution/${distribution.distributionId}`,
            },
          },
        })
      );

      new cdk.CfnOutput(this, "CloudFrontDomain", {
        value: distribution.distributionDomainName,
        description: "CloudFront distribution domain",
      });
      new cdk.CfnOutput(this, "CloudFrontDistributionId", {
        value: distribution.distributionId,
        description: "CloudFront distribution ID — for cache invalidations",
      });
    } else {
      this.distributionDomainName = alb.loadBalancerDnsName;
      new cdk.CfnOutput(this, "AppUrl", {
        value: `http://${alb.loadBalancerDnsName}:8080`,
        description: "Direct ALB URL (CloudFront skipped — pending account verification)",
      });
    }

    // ── CodeDeploy ────────────────────────────────────────────
    const codeDeployApp = new codedeploy.ServerApplication(this, "CodeDeployApp", {
      applicationName: `pfa-api-${stage}`,
    });

    const deploymentGroup = new codedeploy.ServerDeploymentGroup(
      this,
      "CodeDeployGroup",
      {
        application: codeDeployApp,
        deploymentGroupName: `pfa-api-dg-${stage}`,
        autoScalingGroups: [asg],
        deploymentConfig: isProd
          ? codedeploy.ServerDeploymentConfig.ONE_AT_A_TIME
          : codedeploy.ServerDeploymentConfig.ALL_AT_ONCE,
        // Grant the deployment group read access to the artifacts bucket
        role: new iam.Role(this, "CodeDeployRole", {
          roleName: `pfa-codedeploy-role-${stage}`,
          assumedBy: new iam.ServicePrincipal("codedeploy.amazonaws.com"),
          managedPolicies: [
            iam.ManagedPolicy.fromAwsManagedPolicyName(
              "service-role/AWSCodeDeployRole"
            ),
          ],
        }),
        autoRollback: {
          failedDeployment: true,
          stoppedDeployment: true,
        },
      }
    );
    artifactsBucket.grantRead(deploymentGroup.role!);

    // ── CloudWatch Alarms ─────────────────────────────────────
    // ALB 5xx error rate alarm
    const alb5xxAlarm = new cloudwatch.Alarm(this, "Alb5xxAlarm", {
      alarmName: `pfa-alb-5xx-${stage}`,
      alarmDescription: "ALB HTTP 5xx errors > 10 in 5 minutes",
      metric: alb.metrics.httpCodeElb(elbv2.HttpCodeElb.ELB_5XX_COUNT, {
        period: cdk.Duration.minutes(5),
        statistic: "sum",
      }),
      threshold: 10,
      evaluationPeriods: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    alb5xxAlarm.addAlarmAction(new cw_actions.SnsAction(alarmTopic));

    // Target response time alarm (p99 > 3s)
    const latencyAlarm = new cloudwatch.Alarm(this, "LatencyAlarm", {
      alarmName: `pfa-alb-latency-${stage}`,
      alarmDescription: "ALB p99 response time > 3s",
      metric: alb.metrics.targetResponseTime({
        period: cdk.Duration.minutes(5),
        statistic: "p99",
      }),
      threshold: 3,
      evaluationPeriods: 3,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    latencyAlarm.addAlarmAction(new cw_actions.SnsAction(alarmTopic));

    // ASG CPU alarm
    // NOTE: AutoScalingGroup in CDK v2 does not expose metricCpuUtilization();
    // use the raw CloudWatch EC2 metric scoped to the ASG name instead.
    const cpuAlarm = new cloudwatch.Alarm(this, "CpuAlarm", {
      alarmName: `pfa-asg-cpu-${stage}`,
      alarmDescription: "ASG average CPU > 85% for 10 minutes",
      metric: new cloudwatch.Metric({
        namespace: "AWS/EC2",
        metricName: "CPUUtilization",
        dimensionsMap: { AutoScalingGroupName: asg.autoScalingGroupName },
        period: cdk.Duration.minutes(5),
        statistic: "Average",
      }),
      threshold: 85,
      evaluationPeriods: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    cpuAlarm.addAlarmAction(new cw_actions.SnsAction(alarmTopic));

    // Unhealthy host count alarm
    const unhealthyHostsAlarm = new cloudwatch.Alarm(this, "UnhealthyHostsAlarm", {
      alarmName: `pfa-unhealthy-hosts-${stage}`,
      alarmDescription: "One or more ALB targets are unhealthy",
      metric: targetGroup.metrics.unhealthyHostCount({
        period: cdk.Duration.minutes(5),
        statistic: "Maximum",
      }),
      threshold: 0,
      evaluationPeriods: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    unhealthyHostsAlarm.addAlarmAction(new cw_actions.SnsAction(alarmTopic));

    // ── Outputs ───────────────────────────────────────────────
    new cdk.CfnOutput(this, "FrontendBucketName", {
      value: frontendBucket.bucketName,
      description: "S3 bucket for Next.js static assets (sync target for CI)",
    });
    new cdk.CfnOutput(this, "AlbDnsName", {
      value: alb.loadBalancerDnsName,
      description: "ALB DNS name",
    });
    new cdk.CfnOutput(this, "CodeDeployAppName", {
      value: codeDeployApp.applicationName,
    });
    new cdk.CfnOutput(this, "CodeDeployGroupName", {
      value: deploymentGroup.deploymentGroupName,
    });
    new cdk.CfnOutput(this, "AlarmTopicArn", {
      value: alarmTopic.topicArn,
    });

    if (domainName && !skipCloudFront) {
      new cdk.CfnOutput(this, "CustomDomainUrl", {
        value: `https://${domainName}`,
        description: "Production application URL",
      });
    }

    // Suppress unused-variable warnings for void references
    void appLogGroup;
    void cpuAlarm;
    void latencyAlarm;
    void alb5xxAlarm;
    void unhealthyHostsAlarm;
  }
}

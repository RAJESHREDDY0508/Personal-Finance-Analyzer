/**
 * Network Stack — VPC, subnets, security groups.
 * 2 public subnets (ALB, NAT GW) + 2 private subnets (EC2, RDS, MSK).
 */
import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import { Construct } from "constructs";

interface NetworkStackProps extends cdk.StackProps {
  stage: string;
}

export class PfaNetworkStack extends cdk.Stack {
  public readonly vpc: ec2.Vpc;
  public readonly appSecurityGroup: ec2.SecurityGroup;
  public readonly albSecurityGroup: ec2.SecurityGroup;
  public readonly dbSecurityGroup: ec2.SecurityGroup;
  public readonly kafkaSecurityGroup: ec2.SecurityGroup;

  constructor(scope: Construct, id: string, props: NetworkStackProps) {
    super(scope, id, props);

    const { stage } = props;

    // ── VPC ─────────────────────────────────────────────────
    this.vpc = new ec2.Vpc(this, "PfaVpc", {
      vpcName: `pfa-vpc-${stage}`,
      maxAzs: 2,
      natGateways: 1,
      subnetConfiguration: [
        {
          name: "Public",
          subnetType: ec2.SubnetType.PUBLIC,
          cidrMask: 24,
        },
        {
          name: "Private",
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
          cidrMask: 24,
        },
      ],
    });

    // ── Security Groups ──────────────────────────────────────
    // ALB — accepts HTTPS from internet
    this.albSecurityGroup = new ec2.SecurityGroup(this, "AlbSg", {
      vpc: this.vpc,
      description: "ALB security group",
      securityGroupName: `pfa-alb-sg-${stage}`,
    });
    this.albSecurityGroup.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(80));
    this.albSecurityGroup.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(443));

    // App EC2 — accepts traffic from ALB only
    this.appSecurityGroup = new ec2.SecurityGroup(this, "AppSg", {
      vpc: this.vpc,
      description: "App EC2 security group",
      securityGroupName: `pfa-app-sg-${stage}`,
    });
    this.appSecurityGroup.addIngressRule(
      this.albSecurityGroup,
      ec2.Port.tcp(8000),
      "FastAPI from ALB"
    );

    // DB — accepts traffic from App only
    this.dbSecurityGroup = new ec2.SecurityGroup(this, "DbSg", {
      vpc: this.vpc,
      description: "RDS PostgreSQL security group",
      securityGroupName: `pfa-db-sg-${stage}`,
    });
    this.dbSecurityGroup.addIngressRule(
      this.appSecurityGroup,
      ec2.Port.tcp(5432),
      "PostgreSQL from App"
    );

    // Kafka — accepts traffic from App only
    this.kafkaSecurityGroup = new ec2.SecurityGroup(this, "KafkaSg", {
      vpc: this.vpc,
      description: "MSK Kafka security group",
      securityGroupName: `pfa-kafka-sg-${stage}`,
    });
    this.kafkaSecurityGroup.addIngressRule(
      this.appSecurityGroup,
      ec2.Port.tcp(9092),
      "Kafka from App"
    );

    // ── Outputs ─────────────────────────────────────────────
    new cdk.CfnOutput(this, "VpcId", { value: this.vpc.vpcId });
  }
}

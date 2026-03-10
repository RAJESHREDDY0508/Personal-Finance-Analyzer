#!/usr/bin/env node
import "source-map-support/register";
import * as cdk from "aws-cdk-lib";
import { PfaNetworkStack } from "../lib/network-stack";
import { PfaDataStack } from "../lib/data-stack";
import { PfaAppStack } from "../lib/app-stack";

const app = new cdk.App();

const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION || "us-east-1",
};

const stage = (app.node.tryGetContext("stage") as string) || "dev";

// ── Network (VPC, subnets, SGs) ──────────────────────────────
const networkStack = new PfaNetworkStack(app, `PfaNetwork-${stage}`, {
  env,
  stage,
});

// ── Data (RDS, MSK, S3 buckets) ───────────────────────────────
const dataStack = new PfaDataStack(app, `PfaData-${stage}`, {
  env,
  stage,
  vpc: networkStack.vpc,
  dbSecurityGroup: networkStack.dbSecurityGroup,
  kafkaSecurityGroup: networkStack.kafkaSecurityGroup,
});
dataStack.addDependency(networkStack);

// ── App (EC2 ASG, ALB, CloudFront, CodeDeploy, CloudWatch) ────
const appStack = new PfaAppStack(app, `PfaApp-${stage}`, {
  env,
  stage,
  vpc: networkStack.vpc,
  appSecurityGroup: networkStack.appSecurityGroup,
  albSecurityGroup: networkStack.albSecurityGroup,
  dbSecret: dataStack.dbSecret,
  statementsBucket: dataStack.statementsBucket,
  reportsBucket: dataStack.reportsBucket,
  artifactsBucket: dataStack.artifactsBucket,
});
appStack.addDependency(dataStack);

app.synth();

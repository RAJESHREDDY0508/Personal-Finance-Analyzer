# AWS Deployment Guide — PowerShell Edition

Complete guide to deploy the AI Personal Finance Analyzer to AWS from a
**Windows PowerShell** terminal. Every command is written for PowerShell 5.1+
(Windows built-in) or PowerShell 7+. Do **not** run these in CMD or Git Bash —
syntax differs.

> **Resuming?** If you already ran some steps, jump to the section you need.
> Current state after the first attempt: PfaNetwork-dev ✅ | PfaData-dev ❌ (deleted, ready to retry) | PfaApp-dev ❌ (never ran).

---

## Architecture Overview

```
GitHub push → Actions CI → CodeDeploy → EC2 ASG (FastAPI + Kafka workers)
                        → S3 sync    → CloudFront (Next.js static)

Internet ──► Route 53 (optional) ──► CloudFront
                                         ├── /*      ──► S3 (Next.js static)
                                         └── /api/*  ──► ALB ──► EC2 ASG
                                                    (private subnet)
                                                       ├── RDS PostgreSQL
                                                       └── MSK Kafka
```

**Three CDK stacks (deploy in order):**
| Stack | Contents |
|---|---|
| `PfaNetwork-dev` | VPC, subnets, NAT gateways, security groups |
| `PfaData-dev` | RDS PostgreSQL, MSK Kafka, S3 buckets |
| `PfaApp-dev` | EC2 ASG, ALB, CloudFront, CodeDeploy, CloudWatch |

---

## Prerequisites

Open **PowerShell** (Win+X → Windows PowerShell) and verify:

```powershell
aws --version        # aws-cli/2.x
node --version       # v20.x
cdk --version        # 2.x
git --version
```

Install anything missing:
- AWS CLI v2: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
- Node 20: https://nodejs.org/
- CDK: `npm install -g aws-cdk`

---

## Step 1 — Configure AWS CLI

```powershell
aws configure
# AWS Access Key ID:     <your root or admin IAM key>
# AWS Secret Access Key: <secret>
# Default region name:   us-east-1
# Default output format: json
```

Verify it works:
```powershell
aws sts get-caller-identity
```

Expected output includes your `Account` number — note it, you'll need it for bootstrap.

---

## Step 2 — Set SSM Parameters (one-time per stage)

The backend reads secrets from SSM Parameter Store at runtime. Run this
**before** CDK deploy so the stacks can reference them.

> **Note:** The setup script (`infrastructure/scripts/setup-ssm-params.sh`) is
> bash-only. Use the PowerShell commands below instead.

### 2a — Generate JWT secrets

Run this in PowerShell to generate two random secrets:
```powershell
$jwtSecret     = [System.Convert]::ToHexString([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
$jwtRefresh    = [System.Convert]::ToHexString([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
Write-Host "JWT_SECRET:  $jwtSecret"
Write-Host "JWT_REFRESH: $jwtRefresh"
```

Copy both values — you'll paste them below.

### 2b — Write all SSM parameters

Replace every `<...>` placeholder with your real value, then run each block:

```powershell
$STAGE  = "dev"
$REGION = "us-east-1"

# JWT secrets (use values from Step 2a)
aws ssm put-parameter --region $REGION `
  --name "/pfa/$STAGE/jwt-secret" `
  --value "<paste JWT_SECRET here>" `
  --type SecureString --overwrite

aws ssm put-parameter --region $REGION `
  --name "/pfa/$STAGE/jwt-refresh-secret" `
  --value "<paste JWT_REFRESH here>" `
  --type SecureString --overwrite

# OpenAI  (https://platform.openai.com/api-keys)
aws ssm put-parameter --region $REGION `
  --name "/pfa/$STAGE/openai-api-key" `
  --value "sk-..." `
  --type SecureString --overwrite

# Stripe secret key  (https://dashboard.stripe.com/test/apikeys)
aws ssm put-parameter --region $REGION `
  --name "/pfa/$STAGE/stripe-secret-key" `
  --value "sk_test_..." `
  --type SecureString --overwrite

# Stripe webhook secret — use the whsec_ value from Step 6 (Stripe CLI)
# For now set a placeholder; update it after Step 6
aws ssm put-parameter --region $REGION `
  --name "/pfa/$STAGE/stripe-webhook-secret" `
  --value "whsec_placeholder" `
  --type SecureString --overwrite

# Stripe price ID — price_... from your Stripe dashboard Products page
aws ssm put-parameter --region $REGION `
  --name "/pfa/$STAGE/stripe-price-id" `
  --value "price_..." `
  --type SecureString --overwrite

# SES sender email — must be verified in AWS SES before emails work
aws ssm put-parameter --region $REGION `
  --name "/pfa/$STAGE/ses-sender-email" `
  --value "noreply@yourdomain.com" `
  --type SecureString --overwrite

# These two are set AFTER CDK deploy (Step 8) — skip for now
# /pfa/dev/kafka-bootstrap-servers
# /pfa/dev/api-url
```

Verify the parameters were saved:
```powershell
aws ssm get-parameters-by-path `
  --path "/pfa/$STAGE" `
  --region $REGION `
  --query "Parameters[].Name" `
  --output table
```

---

## Step 3 — Fix Broken Stacks (ROLLBACK_COMPLETE cleanup)

> **Skip this step** if you are doing a brand new deployment with no prior
> attempt. If PfaData-dev is stuck in `ROLLBACK_COMPLETE`, you must delete it
> before CDK can redeploy.

### Delete stacks that failed

```powershell
# Check current stack statuses
aws cloudformation describe-stacks `
  --query "Stacks[?contains(StackName,'pfa') || contains(StackName,'Pfa')].{Name:StackName,Status:StackStatus}" `
  --region us-east-1 `
  --output table

# Delete the failed data stack (safe — PfaNetwork-dev is untouched)
aws cloudformation delete-stack `
  --stack-name PfaData-dev `
  --region us-east-1

# Wait for deletion to complete (~2 min)
Write-Host "Waiting for PfaData-dev deletion..."
aws cloudformation wait stack-delete-complete `
  --stack-name PfaData-dev `
  --region us-east-1
Write-Host "PfaData-dev deleted."
```

---

## Step 4 — CDK Bootstrap (one-time per account/region)

```powershell
Set-Location "C:\Users\rajes\Desktop\projects\AI Personal Finance Analyzer\infrastructure"

$ACCOUNT = (aws sts get-caller-identity --query Account --output text)
$REGION  = "us-east-1"
$STAGE   = "dev"

Write-Host "Bootstrapping account $ACCOUNT in $REGION..."

npx cdk bootstrap "aws://$ACCOUNT/$REGION" --context stage=$STAGE
```

Expected: `CDK bootstrap stack has been deployed.` (or "already up to date").

---

## Step 5 — CDK Deploy All Stacks

Make sure you are in the `infrastructure/` directory:

```powershell
Set-Location "C:\Users\rajes\Desktop\projects\AI Personal Finance Analyzer\infrastructure"
```

Deploy all three stacks in dependency order:

```powershell
npx cdk deploy --all --context stage=dev --require-approval never
```

This takes **25–40 minutes** — MSK Kafka is the slowest resource (~20 min).

You will see progress like:
```
PfaNetwork-dev: deploying...   ✅  (~3 min)
PfaData-dev:    deploying...   ✅  (~25 min, MSK dominates)
PfaApp-dev:     deploying...   ✅  (~8 min)
```

### If you want to deploy one stack at a time (easier to debug):

```powershell
# Stack 1 — already deployed, skip unless you need to update it
npx cdk deploy PfaNetwork-dev --context stage=dev --require-approval never

# Stack 2 — was broken, now fixed
npx cdk deploy PfaData-dev --context stage=dev --require-approval never

# Stack 3 — depends on PfaData-dev
npx cdk deploy PfaApp-dev --context stage=dev --require-approval never
```

### Capture the outputs

After all stacks deploy, capture the key output values:

```powershell
# CloudFront distribution URL (used for api-url SSM param and frontend)
$CF_URL = (aws cloudformation describe-stacks `
  --stack-name PfaApp-dev `
  --query "Stacks[0].Outputs[?OutputKey=='CloudFrontUrl'].OutputValue" `
  --output text `
  --region us-east-1)
Write-Host "CloudFront URL: $CF_URL"

# Kafka bootstrap servers
$KAFKA = (aws cloudformation describe-stacks `
  --stack-name PfaData-dev `
  --query "Stacks[0].Outputs[?OutputKey=='KafkaBootstrapServers'].OutputValue" `
  --output text `
  --region us-east-1)
Write-Host "Kafka: $KAFKA"

# ALB DNS name
$ALB = (aws cloudformation describe-stacks `
  --stack-name PfaApp-dev `
  --query "Stacks[0].Outputs[?OutputKey=='AlbDnsName'].OutputValue" `
  --output text `
  --region us-east-1)
Write-Host "ALB: $ALB"
```

---

## Step 6 — Update SSM Params with Real Deploy Values

Now that the stacks are live, fill in the two params you skipped earlier:

```powershell
$STAGE  = "dev"
$REGION = "us-east-1"

# Kafka bootstrap servers (from Step 5 output)
aws ssm put-parameter --region $REGION `
  --name "/pfa/$STAGE/kafka-bootstrap-servers" `
  --value $KAFKA `
  --type SecureString --overwrite

# API URL = CloudFront URL (no trailing slash)
aws ssm put-parameter --region $REGION `
  --name "/pfa/$STAGE/api-url" `
  --value "https://$CF_URL" `
  --type String --overwrite
```

---

## Step 7 — Configure GitHub Actions IAM User

The GitHub Actions workflows (`deploy-backend.yml`, `deploy-frontend.yml`) need
an IAM user with permissions to push to S3, trigger CodeDeploy, run SSM
commands, and invalidate CloudFront.

### 7a — Create IAM policy file

Save the policy to a temporary JSON file (avoids PowerShell JSON escaping issues):

```powershell
$ACCOUNT = (aws sts get-caller-identity --query Account --output text)
$REGION  = "us-east-1"
$STAGE   = "dev"

$policyJson = @"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3Artifacts",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::pfa-artifacts-${STAGE}",
        "arn:aws:s3:::pfa-artifacts-${STAGE}/*",
        "arn:aws:s3:::pfa-frontend-${STAGE}",
        "arn:aws:s3:::pfa-frontend-${STAGE}/*"
      ]
    },
    {
      "Sid": "CodeDeploy",
      "Effect": "Allow",
      "Action": [
        "codedeploy:CreateDeployment",
        "codedeploy:GetDeployment",
        "codedeploy:GetDeploymentConfig",
        "codedeploy:RegisterApplicationRevision"
      ],
      "Resource": "*"
    },
    {
      "Sid": "SSMRunCommand",
      "Effect": "Allow",
      "Action": [
        "ssm:SendCommand",
        "ssm:GetCommandInvocation"
      ],
      "Resource": "*"
    },
    {
      "Sid": "SSMGetParams",
      "Effect": "Allow",
      "Action": ["ssm:GetParameter", "ssm:GetParametersByPath"],
      "Resource": "arn:aws:ssm:${REGION}:${ACCOUNT}:parameter/pfa/*"
    },
    {
      "Sid": "AutoScaling",
      "Effect": "Allow",
      "Action": ["autoscaling:DescribeAutoScalingGroups"],
      "Resource": "*"
    },
    {
      "Sid": "CloudFrontInvalidation",
      "Effect": "Allow",
      "Action": ["cloudfront:CreateInvalidation"],
      "Resource": "*"
    },
    {
      "Sid": "CloudFormationRead",
      "Effect": "Allow",
      "Action": ["cloudformation:DescribeStacks"],
      "Resource": "*"
    }
  ]
}
"@

# Write to temp file
$policyFile = "$env:TEMP\pfa-github-policy.json"
$policyJson | Set-Content -Path $policyFile -Encoding UTF8
Write-Host "Policy written to $policyFile"
```

### 7b — Create the policy and attach it

```powershell
# Create the managed policy in IAM
$policyArn = (aws iam create-policy `
  --policy-name pfa-github-actions-policy `
  --policy-document "file://$policyFile" `
  --query "Policy.Arn" `
  --output text)
Write-Host "Policy ARN: $policyArn"

# Attach it to the IAM user created earlier
aws iam attach-user-policy `
  --user-name pfa-github-actions `
  --policy-arn $policyArn

Write-Host "Policy attached to pfa-github-actions user."
```

> **If you already ran this and got MalformedPolicyDocument:** The issue was
> PowerShell here-string encoding. The file-based approach above avoids it.
> If the policy already exists, run:
> ```powershell
> # Get existing policy ARN
> $policyArn = (aws iam list-policies --scope Local `
>   --query "Policies[?PolicyName=='pfa-github-actions-policy'].Arn" `
>   --output text)
> # Attach it
> aws iam attach-user-policy --user-name pfa-github-actions --policy-arn $policyArn
> ```

### 7c — Verify the user has the policy

```powershell
aws iam list-attached-user-policies `
  --user-name pfa-github-actions `
  --output table
```

---

## Step 8 — Add GitHub Actions Secrets

Go to: **https://github.com/RAJESHREDDY0508/Personal-Finance-Analyzer/settings/secrets/actions**

Click **New repository secret** and add these two secrets:

| Secret Name | Value |
|---|---|
| `AWS_ACCESS_KEY_ID` | `AKIARKFWZVFD3EJZLHM4` |
| `AWS_SECRET_ACCESS_KEY` | (the secret key for that access key) |

> ⚠️ **Security note:** The access key ID was shown in the terminal session.
> If you are concerned it was exposed, rotate it:
> ```powershell
> # Create new key
> aws iam create-access-key --user-name pfa-github-actions
> # Delete the old key after updating GitHub secrets
> aws iam delete-access-key --user-name pfa-github-actions --access-key-id AKIARKFWZVFD3EJZLHM4
> ```

---

## Step 9 — EC2 Instance Setup

The EC2 instances launched by the Auto Scaling Group need the application
installed. SSH into a running instance and run the setup script.

### 9a — Find a running instance

```powershell
$STAGE = "dev"

$INSTANCE_ID = (aws autoscaling describe-auto-scaling-groups `
  --auto-scaling-group-names "pfa-asg-$STAGE" `
  --query "AutoScalingGroups[0].Instances[0].InstanceId" `
  --output text `
  --region us-east-1)
Write-Host "Instance: $INSTANCE_ID"
```

### 9b — Get the public IP

```powershell
$PUBLIC_IP = (aws ec2 describe-instances `
  --instance-ids $INSTANCE_ID `
  --query "Reservations[0].Instances[0].PublicIpAddress" `
  --output text `
  --region us-east-1)
Write-Host "SSH: ec2-user@$PUBLIC_IP"
```

### 9c — SSH and run setup

```powershell
# Use the key pair that was configured in the CDK app stack
ssh -i "~/.ssh/pfa-key.pem" "ec2-user@$PUBLIC_IP"
```

Once on the instance, run:
```bash
# Bootstrap the EC2 instance (installs Python 3.12, systemd units, pulls code)
curl -sSL https://raw.githubusercontent.com/RAJESHREDDY0508/Personal-Finance-Analyzer/main/infrastructure/scripts/setup-ec2.sh | sudo bash -s -- dev
```

> Alternatively, if SSM Session Manager is configured (preferred — no SSH key needed):
> ```powershell
> aws ssm start-session --target $INSTANCE_ID --region us-east-1
> ```

---

## Step 10 — Stripe Webhook Setup

### 10a — Get the Stripe CLI

```powershell
# Check if already installed
stripe --version

# If not installed (Windows via Scoop):
scoop bucket add stripe https://github.com/stripe/scoop-stripe-cli.git
scoop install stripe

# Or download the exe from https://github.com/stripe/stripe-cli/releases
# and add to PATH
```

### 10b — Login and get webhook secret

```powershell
stripe login
```

A browser window opens — authorize the CLI.

### 10c — Register your production webhook endpoint

```powershell
# Create a webhook endpoint pointing to your CloudFront/ALB URL
stripe webhooks create `
  --url "https://$CF_URL/api/v1/billing/webhook" `
  --events "checkout.session.completed,customer.subscription.updated,customer.subscription.deleted"
```

Copy the `whsec_...` secret from the output, then update SSM:

```powershell
aws ssm put-parameter --region us-east-1 `
  --name "/pfa/dev/stripe-webhook-secret" `
  --value "whsec_..." `
  --type SecureString --overwrite
```

### 10d — Forward webhooks locally (for testing only)

```powershell
stripe listen --forward-to http://localhost:8000/api/v1/billing/webhook
```

---

## Step 11 — Verify the Deployment

```powershell
# Health check (replace with your actual CloudFront URL)
Invoke-RestMethod -Uri "https://$CF_URL/api/v1/health"
# Expected: { status = "ok"; environment = "production" }

# Or use curl (also works in PowerShell 7+)
curl "https://$CF_URL/api/v1/health"
```

Check that all SSM params are set:
```powershell
aws ssm get-parameters-by-path `
  --path "/pfa/dev" `
  --region us-east-1 `
  --query "Parameters[].{Name:Name,Type:Type}" `
  --output table
```

Expected parameters:
```
/pfa/dev/jwt-secret
/pfa/dev/jwt-refresh-secret
/pfa/dev/openai-api-key
/pfa/dev/stripe-secret-key
/pfa/dev/stripe-webhook-secret
/pfa/dev/stripe-price-id
/pfa/dev/ses-sender-email
/pfa/dev/kafka-bootstrap-servers
/pfa/dev/api-url
```

---

## Step 12 — Push Code to Trigger CI/CD

With GitHub secrets set, any push to `main` automatically:
1. Runs tests (`ci.yml`)
2. Deploys backend via CodeDeploy (`deploy-backend.yml`)
3. Builds and syncs frontend to S3 + CloudFront (`deploy-frontend.yml`)

```powershell
Set-Location "C:\Users\rajes\Desktop\projects\AI Personal Finance Analyzer"

git add infrastructure/lib/data-stack.ts docs/aws-deploy.md
git commit -m "fix: MSK requires >=2 client subnets even for 1 broker node

AWS MSK API rejects clientSubnets arrays with only 1 entry regardless
of numberOfBrokerNodes. Changed dev config from [privateSubnetIds[0]]
to privateSubnetIds.slice(0, 2) to satisfy the API constraint.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"

git push origin main
```

Monitor the deployment in GitHub Actions:
```
https://github.com/RAJESHREDDY0508/Personal-Finance-Analyzer/actions
```

---

## Troubleshooting

### `ROLLBACK_COMPLETE` — can't redeploy a stack

```powershell
# Delete the stuck stack, then re-run cdk deploy
aws cloudformation delete-stack --stack-name PfaData-dev --region us-east-1
aws cloudformation wait stack-delete-complete --stack-name PfaData-dev --region us-east-1
npx cdk deploy PfaData-dev --context stage=dev --require-approval never
```

### MSK "Specify either two or three client subnets"

**Root cause:** `data-stack.ts` was passing only 1 subnet for dev.
**Fixed in this repo** — `clientSubnets: privateSubnetIds.slice(0, 2)` now runs for all stages.

### IAM `MalformedPolicyDocument` when using PowerShell

**Root cause:** PowerShell here-strings passed directly to `aws --policy-document` can include BOM characters or extra whitespace.
**Fix:** Write the JSON to a temp file first, then pass `file://path` (see Step 7).

### `$VAR = $(aws ...)` not recognized

That is bash syntax. In PowerShell:
```powershell
# Correct PowerShell syntax
$VAR = (aws sts get-caller-identity --query Account --output text)

# NOT this (bash only):
# VAR=$(aws ...)
```

### Line continuation in PowerShell

Use a backtick `` ` `` at the end of the line (not `\`):
```powershell
aws ssm put-parameter `
  --name "/pfa/dev/jwt-secret" `
  --value "abc123" `
  --type SecureString
```

### CDK diff fails — "The security token included in the request is invalid"

Run `aws configure` again and confirm your Access Key ID and Secret are correct.

### GitHub Actions deploy fails — "Unable to locate credentials"

The `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` secrets may be missing or
wrong in GitHub repo settings. Verify at:
`https://github.com/RAJESHREDDY0508/Personal-Finance-Analyzer/settings/secrets/actions`

### Backend health check returns 502/504

The ALB target group health check is failing. Check:
```powershell
# View recent backend logs via SSM
aws ssm send-command `
  --instance-ids $INSTANCE_ID `
  --document-name "AWS-RunShellScript" `
  --parameters '{"commands":["journalctl -u pfa-api -n 50 --no-pager"]}' `
  --region us-east-1 `
  --output text
```

---

## Quick Reference — Current State After First Attempt

| Item | Status | Action Needed |
|---|---|---|
| PfaNetwork-dev CDK stack | ✅ Deployed | None |
| PfaData-dev CDK stack | ❌ ROLLBACK_COMPLETE | Delete → fix MSK → redeploy |
| PfaApp-dev CDK stack | ❌ Never ran | Will deploy after PfaData succeeds |
| MSK subnet bug | ✅ Fixed in code | Commit and redeploy |
| IAM user `pfa-github-actions` | ✅ Created, ❌ no policy | Attach policy (Step 7) |
| GitHub secrets | ❌ Not added | Add in Step 8 |
| SSM `kafka-bootstrap-servers` | ⚠️ Empty string | Update after PfaData deploy |
| SSM `api-url` | ⚠️ Empty string | Update after PfaApp deploy |
| Code on GitHub | ✅ Pushed to main | — |

---

## Resuming From Current State — Exact Commands

Run these in order from PowerShell, replacing the project root path if needed:

```powershell
# 0. Navigate to project
Set-Location "C:\Users\rajes\Desktop\projects\AI Personal Finance Analyzer"

# 1. Commit the MSK fix
git add infrastructure/lib/data-stack.ts docs/aws-deploy.md
git commit -m "fix: MSK clientSubnets must have >=2 entries regardless of broker count"
git push origin main

# 2. Delete the failed PfaData-dev stack
aws cloudformation delete-stack --stack-name PfaData-dev --region us-east-1
aws cloudformation wait stack-delete-complete --stack-name PfaData-dev --region us-east-1

# 3. Redeploy (PfaNetwork-dev skipped — already deployed and unchanged)
Set-Location ".\infrastructure"
npx cdk deploy PfaData-dev PfaApp-dev --context stage=dev --require-approval never

# 4. Capture outputs
$CF_URL = (aws cloudformation describe-stacks `
  --stack-name PfaApp-dev `
  --query "Stacks[0].Outputs[?OutputKey=='CloudFrontUrl'].OutputValue" `
  --output text --region us-east-1)

$KAFKA = (aws cloudformation describe-stacks `
  --stack-name PfaData-dev `
  --query "Stacks[0].Outputs[?OutputKey=='KafkaBootstrapServers'].OutputValue" `
  --output text --region us-east-1)

Write-Host "CloudFront: https://$CF_URL"
Write-Host "Kafka:      $KAFKA"

# 5. Update SSM with real values
aws ssm put-parameter --region us-east-1 `
  --name "/pfa/dev/kafka-bootstrap-servers" --value $KAFKA `
  --type SecureString --overwrite

aws ssm put-parameter --region us-east-1 `
  --name "/pfa/dev/api-url" --value "https://$CF_URL" `
  --type String --overwrite

# 6. Attach IAM policy to GitHub Actions user
$ACCOUNT = (aws sts get-caller-identity --query Account --output text)
$policyFile = "$env:TEMP\pfa-github-policy.json"
# (run Step 7a to write the policy JSON file, then:)
$policyArn = (aws iam create-policy `
  --policy-name pfa-github-actions-policy `
  --policy-document "file://$policyFile" `
  --query "Policy.Arn" --output text)
aws iam attach-user-policy --user-name pfa-github-actions --policy-arn $policyArn

# 7. Health check
Invoke-RestMethod -Uri "https://$CF_URL/api/v1/health"
```

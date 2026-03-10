# AWS Deployment Guide — End to End

Complete guide to deploy the AI Personal Finance Analyzer to AWS and configure
GitHub Actions for fully-automated CI/CD. Follow the sections in order on a
first deployment.

---

## Architecture Overview

```
GitHub push → Actions CI (test + build) → CodeDeploy → EC2 ASG
                                        → S3 sync   → CloudFront

Internet ──► Route 53 (optional) ──► CloudFront
                                         ├── /* ──────► S3 (Next.js static)
                                         └── /api/* ──► ALB ──► EC2 ASG
                                                                  └── FastAPI
                                                                  └── Kafka Workers
                                                    (private subnet)
                                                       ├── RDS PostgreSQL
                                                       └── MSK Kafka
```

**Three CDK stacks:**
- `PfaNetwork-{stage}` — VPC, subnets, NAT gateways, security groups
- `PfaData-{stage}` — RDS PostgreSQL, MSK Kafka, S3 buckets (statements, reports, artifacts)
- `PfaApp-{stage}` — EC2 ASG, ALB, CloudFront, S3 (frontend), CodeDeploy, CloudWatch alarms

---

## Prerequisites

### Tools (install if missing)

```bash
# AWS CLI v2
# https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
aws --version   # should show aws-cli/2.x

# Node.js 20+
node --version

# CDK CLI
npm install -g aws-cdk
cdk --version   # should show 2.x

# Stripe CLI (for webhook setup)
# https://stripe.com/docs/stripe-cli
stripe --version
```

### Accounts and services needed

| Service | What you need | Where |
|---------|--------------|-------|
| **AWS** | Account with billing enabled | console.aws.amazon.com |
| **OpenAI** | API key (GPT-4o access) | platform.openai.com/api-keys |
| **Stripe** | Account + test + live API keys | dashboard.stripe.com |
| **GitHub** | Repository for your code | github.com |
| **Domain** _(optional)_ | Domain registered in Route 53 or elsewhere | — |

---

## Step 1 — Configure AWS CLI

```bash
aws configure
# AWS Access Key ID: <your-key>
# AWS Secret Access Key: <your-secret>
# Default region: us-east-1
# Default output format: json
```

Verify:

```bash
aws sts get-caller-identity
# Expected: {"UserId": "...", "Account": "123456789012", "Arn": "arn:aws:iam::..."}
```

### IAM permissions required

The account/role you use for CDK deploy needs broad permissions. For a personal
project the simplest option is `AdministratorAccess`. For a team environment
use a scoped deployment role — minimum permissions needed:

<details>
<summary>Minimum CDK deployment policy (click to expand)</summary>

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": "cloudformation:*",          "Resource": "*" },
    { "Effect": "Allow", "Action": "s3:*",                      "Resource": "*" },
    { "Effect": "Allow", "Action": "iam:*",                     "Resource": "*" },
    { "Effect": "Allow", "Action": "ec2:*",                     "Resource": "*" },
    { "Effect": "Allow", "Action": "autoscaling:*",             "Resource": "*" },
    { "Effect": "Allow", "Action": "elasticloadbalancing:*",    "Resource": "*" },
    { "Effect": "Allow", "Action": "cloudfront:*",              "Resource": "*" },
    { "Effect": "Allow", "Action": "rds:*",                     "Resource": "*" },
    { "Effect": "Allow", "Action": "kafka:*",                   "Resource": "*" },
    { "Effect": "Allow", "Action": "secretsmanager:*",          "Resource": "*" },
    { "Effect": "Allow", "Action": "ssm:*",                     "Resource": "*" },
    { "Effect": "Allow", "Action": "codedeploy:*",              "Resource": "*" },
    { "Effect": "Allow", "Action": "cloudwatch:*",              "Resource": "*" },
    { "Effect": "Allow", "Action": "sns:*",                     "Resource": "*" },
    { "Effect": "Allow", "Action": "logs:*",                    "Resource": "*" },
    { "Effect": "Allow", "Action": "ses:*",                     "Resource": "*" },
    { "Effect": "Allow", "Action": "route53:*",                 "Resource": "*" },
    { "Effect": "Allow", "Action": "acm:*",                     "Resource": "*" }
  ]
}
```
</details>

---

## Step 2 — CDK Bootstrap

CDK bootstrap creates an S3 bucket and IAM roles in your account that CDK uses
to store assets during deployment. **Run once per AWS account + region.**

```bash
cd infrastructure

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=us-east-1

npx cdk bootstrap aws://${ACCOUNT}/${REGION} --context stage=dev
```

Expected output ends with:
```
✅  Environment aws://123456789012/us-east-1 bootstrapped.
```

---

## Step 3 — Create SSM Parameter Store Secrets

All runtime secrets (JWT keys, API keys, Stripe keys) are stored in SSM
Parameter Store as `SecureString` values and fetched by EC2 instances at
deployment time. Run the interactive setup script:

```bash
chmod +x infrastructure/scripts/setup-ssm-params.sh
./infrastructure/scripts/setup-ssm-params.sh
```

The script will prompt for:

| SSM Parameter | Description |
|--------------|-------------|
| `/pfa/dev/jwt-secret` | Access token signing key (min 32 chars) |
| `/pfa/dev/jwt-refresh-secret` | Refresh token signing key (different from above) |
| `/pfa/dev/openai-api-key` | OpenAI API key (`sk-...`) |
| `/pfa/dev/stripe-secret-key` | Stripe secret key (`sk_test_...` for dev) |
| `/pfa/dev/stripe-webhook-secret` | Stripe webhook signing secret (`whsec_...`) |
| `/pfa/dev/stripe-price-id` | Stripe Premium price ID (`price_...`) |
| `/pfa/dev/ses-sender-email` | SES verified sender email |
| `/pfa/dev/domain-name` | _(optional)_ Custom domain (`app.example.com`) |
| `/pfa/dev/kafka-bootstrap-servers` | _(set after CDK deploy — skip for now)_ |

### Generate secure JWT secrets

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
# Run twice — one for jwt-secret, one for jwt-refresh-secret
```

### Verify parameters were written

```bash
aws ssm get-parameters-by-path \
  --path /pfa/dev \
  --with-decryption \
  --query 'Parameters[].{Name:Name}' \
  --output table
```

---

## Step 4 — SES Email Verification

The backend sends monthly reports via AWS SES. In sandbox mode (default for
new accounts) you must verify every sender email address.

```bash
# Verify your sender email
aws ses verify-email-identity \
  --email-address noreply@yourdomain.com \
  --region us-east-1
```

Check your inbox for the verification link and click it. Verify it worked:

```bash
aws ses get-identity-verification-attributes \
  --identities noreply@yourdomain.com \
  --query 'VerificationAttributes.*.VerificationStatus' \
  --output text
# Expected: Success
```

> **Production:** Request SES production access (removes sandbox restrictions)
> in the AWS console → SES → Account dashboard → Request production access.

---

## Step 5 — Create Stripe Product & Price

```bash
# Login to Stripe and create the Premium product + price
stripe login

# Create a product
stripe products create \
  --name "AI Finance Analyzer Premium" \
  --description "Unlimited AI categorization, anomaly detection, and budget predictions"

# Create a recurring price ($5/month) — paste the product ID from above
stripe prices create \
  --product prod_XXXXXXXXXX \
  --currency usd \
  --unit-amount 500 \
  --recurring[interval]=month
# Note the price_... ID and update SSM: /pfa/dev/stripe-price-id
```

Update the SSM parameter with the real price ID:

```bash
aws ssm put-parameter \
  --name /pfa/dev/stripe-price-id \
  --value "price_XXXXXXXXXX" \
  --type SecureString \
  --overwrite
```

---

## Step 6 — Deploy CDK Infrastructure

```bash
cd infrastructure

# Preview what will be created (no changes made)
npx cdk diff --all --context stage=dev

# Deploy all three stacks (takes ~15-20 minutes on first run)
npx cdk deploy --all --context stage=dev --require-approval never
```

You'll see output as each stack deploys. On success:

```
✅  PfaNetwork-dev

✅  PfaData-dev
Outputs:
PfaData-dev.KafkaBootstrapServers = b-1.pfa-kafka-dev.xxxxx.c2.kafka.us-east-1.amazonaws.com:9094,...
PfaData-dev.StatementsBucketName  = pfa-statements-dev
PfaData-dev.ReportsBucketName     = pfa-reports-dev
PfaData-dev.ArtifactsBucketName   = pfa-artifacts-dev
PfaData-dev.DbSecretArn           = arn:aws:secretsmanager:...

✅  PfaApp-dev
Outputs:
PfaApp-dev.CloudFrontDomain       = d1234abcd.cloudfront.net
PfaApp-dev.CloudFrontDistributionId = E1ABCDEF12345
PfaApp-dev.AlbDnsName             = pfa-alb-dev-xxxx.us-east-1.elb.amazonaws.com
PfaApp-dev.FrontendBucketName     = pfa-frontend-dev
PfaApp-dev.CodeDeployAppName      = pfa-api-dev
PfaApp-dev.CodeDeployGroupName    = pfa-api-dg-dev
```

**Save these output values** — you'll need them in the next steps.

> **Cost note:** MSK (`kafka.m5.large`) costs ~$0.21/hr per broker. RDS
> `db.t3.medium` costs ~$0.068/hr. Budget ~$10-15/day for a dev stack.
> Destroy when not needed: `npx cdk destroy --all --context stage=dev`

---

## Step 7 — Post-Deploy: Update SSM with Kafka and API URL

### 7a — Update Kafka bootstrap servers

Copy the `KafkaBootstrapServers` value from the CDK output above:

```bash
KAFKA=$(aws cloudformation describe-stacks \
  --stack-name PfaData-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`KafkaBootstrapServers`].OutputValue' \
  --output text)

echo "Kafka: $KAFKA"

aws ssm put-parameter \
  --name /pfa/dev/kafka-bootstrap-servers \
  --value "$KAFKA" \
  --type SecureString \
  --overwrite
```

### 7b — Set the API URL (used by the frontend build in CI)

The frontend CI workflow reads `/pfa/dev/api-url` to embed the correct API URL
in the Next.js build. Set it to your CloudFront domain:

```bash
# Without custom domain — use CloudFront URL
CF_DOMAIN=$(aws cloudformation describe-stacks \
  --stack-name PfaApp-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`CloudFrontDomain`].OutputValue' \
  --output text)

aws ssm put-parameter \
  --name /pfa/dev/api-url \
  --value "https://${CF_DOMAIN}" \
  --type String \
  --overwrite

# With custom domain (after Route 53 setup in Step 9)
# aws ssm put-parameter --name /pfa/dev/api-url \
#   --value "https://app.yourdomain.com" --type String --overwrite
```

---

## Step 8 — Configure GitHub Repository Secrets

Go to your GitHub repository → **Settings → Secrets and variables → Actions →
New repository secret** and add:

| Secret name | Value | Description |
|-------------|-------|-------------|
| `AWS_ACCESS_KEY_ID` | Your IAM key ID | Used by all deploy workflows |
| `AWS_SECRET_ACCESS_KEY` | Your IAM secret | Used by all deploy workflows |
| `CODECOV_TOKEN` | From app.codecov.io _(optional)_ | Coverage reporting — CI won't fail without it |

### Minimum IAM permissions for the GitHub Actions IAM user

Create a dedicated IAM user for CI/CD (don't use your admin user):

```bash
# Create the CI user
aws iam create-user --user-name pfa-github-actions

# Attach a policy with the minimum required permissions
aws iam put-user-policy \
  --user-name pfa-github-actions \
  --policy-name pfa-ci-deploy \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": ["s3:PutObject","s3:GetObject","s3:DeleteObject","s3:ListBucket","s3:PutObjectAcl"],
        "Resource": ["arn:aws:s3:::pfa-artifacts-*","arn:aws:s3:::pfa-artifacts-*/*",
                     "arn:aws:s3:::pfa-frontend-*","arn:aws:s3:::pfa-frontend-*/*"]
      },
      {
        "Effect": "Allow",
        "Action": ["codedeploy:CreateDeployment","codedeploy:GetDeployment",
                   "codedeploy:GetDeploymentConfig","codedeploy:GetApplicationRevision",
                   "codedeploy:RegisterApplicationRevision"],
        "Resource": "*"
      },
      {
        "Effect": "Allow",
        "Action": ["autoscaling:DescribeAutoScalingGroups"],
        "Resource": "*"
      },
      {
        "Effect": "Allow",
        "Action": ["ssm:SendCommand","ssm:GetCommandInvocation",
                   "ssm:ListCommandInvocations","ssm:GetParameter"],
        "Resource": "*"
      },
      {
        "Effect": "Allow",
        "Action": ["cloudformation:DescribeStacks"],
        "Resource": "*"
      },
      {
        "Effect": "Allow",
        "Action": ["cloudfront:CreateInvalidation"],
        "Resource": "*"
      }
    ]
  }'

# Create access keys
aws iam create-access-key --user-name pfa-github-actions
# ↑ Copy the AccessKeyId and SecretAccessKey into GitHub secrets
```

---

## Step 9 — (Optional) Custom Domain via Route 53

If you have a domain registered in Route 53:

```bash
# Deploy with domain context — CDK will create ACM cert + CF alias
cd infrastructure
npx cdk deploy PfaApp-dev \
  --context stage=dev \
  --context domainName=app.yourdomain.com \
  --require-approval never
```

CDK will:
1. Request an ACM certificate for `app.yourdomain.com` and `www.app.yourdomain.com`
2. Create Route 53 DNS validation CNAME records automatically
3. Wait for ACM validation (takes 1-5 minutes)
4. Configure CloudFront with the certificate and domain aliases

Then update the API URL SSM param:

```bash
aws ssm put-parameter \
  --name /pfa/dev/api-url \
  --value "https://app.yourdomain.com" \
  --type String \
  --overwrite
```

---

## Step 10 — First Deployment via GitHub Actions

Push your code to the `main` branch to trigger both deploy workflows:

```bash
git add -A
git commit -m "feat: initial production deployment"
git push origin main
```

### What happens automatically

**On every push to `main`:**

```
┌─────────────────────────────────────────────────────────────────┐
│ CI (ci.yml) — runs on every push/PR                             │
│   ├── Backend tests (pytest, 165 tests, ~25s)                   │
│   ├── Frontend TypeScript check + next build                    │
│   └── CDK synth (dry-run, no AWS calls)                         │
└─────────────────────────────────────────────────────────────────┘
                           ↓ if CI passes
┌─────────────────────────────────────────────────────────────────┐
│ deploy-backend.yml — triggered when backend/** changes          │
│   1. Run 165 backend tests (pre-deploy gate)                    │
│   2. Zip backend/ (excluding .pyc, __pycache__, .env)           │
│   3. Upload zip to s3://pfa-artifacts-dev/backend/{sha}.zip     │
│   4. aws deploy create-deployment → CodeDeploy                  │
│      └── EC2 lifecycle hooks:                                   │
│          ├── before-install.sh  (stop service, create user/dirs)│
│          ├── after-install.sh   (pip install, fetch secrets,    │
│          │                       write /etc/pfa/env, systemd)   │
│          ├── start-server.sh   (systemctl restart pfa-api)      │
│          └── validate-service.sh (health check with 6 retries)  │
│   5. SSM Run Command: alembic upgrade head on the EC2 instance  │
│   6. Auto-rollback if any step fails                            │
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│ deploy-frontend.yml — triggered when frontend/** changes        │
│   1. Read NEXT_PUBLIC_API_URL from SSM /pfa/dev/api-url         │
│   2. npm ci + npx tsc --noEmit + npm run build                  │
│   3. aws s3 sync frontend/out → s3://pfa-frontend-dev/          │
│      ├── assets: Cache-Control: max-age=31536000, immutable      │
│      └── HTML:   Cache-Control: max-age=0, must-revalidate      │
│   4. aws cloudfront create-invalidation --paths "/*"            │
└─────────────────────────────────────────────────────────────────┘
```

### Monitor the workflow

Go to your GitHub repo → **Actions** tab to watch the workflows run in real
time.

---

## Step 11 — Configure Stripe Webhooks for Production

Add the production webhook endpoint in Stripe:

1. Go to **https://dashboard.stripe.com/webhooks**
2. Click **Add endpoint**
3. URL: `https://your-cloudfront-domain/api/v1/billing/webhook`
4. Events to listen for: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`
5. Copy the signing secret (`whsec_...`)
6. Update SSM:

```bash
aws ssm put-parameter \
  --name /pfa/dev/stripe-webhook-secret \
  --value "whsec_live_..." \
  --type SecureString \
  --overwrite
```

Then redeploy to pick up the new secret (push any change to `backend/`).

---

## Step 12 — Verify the Production Deployment

```bash
# Get your CloudFront URL
CF_URL=$(aws cloudformation describe-stacks \
  --stack-name PfaApp-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`CloudFrontDomain`].OutputValue' \
  --output text)

echo "App URL: https://$CF_URL"

# 1. Health check via CloudFront → ALB → EC2
curl -s "https://${CF_URL}/api/v1/health" | python -m json.tool
# Expected: {"status": "ok", "environment": "dev"}

# 2. Register a user
curl -s -X POST "https://${CF_URL}/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"email": "prod-test@example.com", "password": "TestPass123!"}' \
  | python -m json.tool

# 3. API docs (only available in non-prod environments)
open "https://${CF_URL}/docs"

# 4. Frontend
open "https://${CF_URL}"
```

---

## Ongoing Operations

### Deploy only backend changes

```bash
# Push a backend change — deploy-backend.yml triggers automatically
git push origin main

# Or trigger manually for a specific stage
# GitHub → Actions → "Deploy Backend" → Run workflow → select stage
```

### Deploy only frontend changes

```bash
# Push a frontend change — deploy-frontend.yml triggers automatically
git push origin main

# Or trigger manually
# GitHub → Actions → "Deploy Frontend" → Run workflow → select stage
```

### View application logs

```bash
# Backend API logs (last 30 minutes)
aws logs filter-log-events \
  --log-group-name /pfa/dev/api \
  --start-time $(date -d '30 minutes ago' +%s000 2>/dev/null || \
                 date -v-30M +%s000) \
  --query 'events[].message' \
  --output text

# Or use CloudWatch Insights (console)
# Logs → Log Insights → /pfa/dev/api → Run query
```

### SSH into EC2 (via SSM Session Manager — no bastion needed)

```bash
# Get an instance ID
INSTANCE_ID=$(aws autoscaling describe-auto-scaling-groups \
  --auto-scaling-group-names pfa-asg-dev \
  --query 'AutoScalingGroups[0].Instances[0].InstanceId' \
  --output text)

# Start session
aws ssm start-session --target "$INSTANCE_ID"

# Once inside:
sudo journalctl -u pfa-api -f         # tail application logs
sudo cat /etc/pfa/env                  # view current environment file
sudo systemctl status pfa-api          # check service status
```

### Run a database migration manually

```bash
INSTANCE_ID=$(aws autoscaling describe-auto-scaling-groups \
  --auto-scaling-group-names pfa-asg-dev \
  --query 'AutoScalingGroups[0].Instances[0].InstanceId' \
  --output text)

aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters '{"commands":["cd /opt/pfa && source /etc/pfa/env && python3.12 -m alembic upgrade head"]}' \
  --output text
```

### Rollback a bad deployment

CodeDeploy auto-rolls back if the `validate-service.sh` health check fails.
For a manual rollback:

```bash
# List recent deployments
aws deploy list-deployments \
  --application-name pfa-api-dev \
  --deployment-group-name pfa-api-dg-dev \
  --query 'deployments[0:5]' \
  --output text

# Redeploy a previous revision (replace with your previous good sha)
PREV_SHA=abc123def456

aws deploy create-deployment \
  --application-name pfa-api-dev \
  --deployment-group-name pfa-api-dg-dev \
  --s3-location "bucket=pfa-artifacts-dev,key=backend/backend-${PREV_SHA}.zip,bundleType=zip" \
  --deployment-config-name CodeDeployDefault.AllAtOnce
```

### Scale the fleet

```bash
# Scale up to 3 instances
aws autoscaling set-desired-capacity \
  --auto-scaling-group-name pfa-asg-dev \
  --desired-capacity 3

# Scale back to 1
aws autoscaling set-desired-capacity \
  --auto-scaling-group-name pfa-asg-dev \
  --desired-capacity 1
```

### Check CloudWatch alarms

```bash
aws cloudwatch describe-alarms \
  --alarm-name-prefix pfa- \
  --query 'MetricAlarms[].{Name:AlarmName,State:StateValue,Reason:StateReason}' \
  --output table
```

---

## Tear Down (to stop AWS costs)

```bash
# WARNING: This deletes all infrastructure. RDS and S3 in prod have RETAIN
# policy — run `aws s3 rb --force` manually to delete prod buckets.

cd infrastructure
npx cdk destroy --all --context stage=dev --force
```

Dev buckets (statements, reports, artifacts, frontend) have `RemovalPolicy.DESTROY`
so CDK will delete them automatically. The RDS final snapshot is NOT created in
dev (set `deletionProtection: false`).

---

## Summary: Full SSM Parameters Reference

All parameters under `/pfa/{stage}/`:

| Parameter | Type | Set by | Required |
|-----------|------|--------|----------|
| `jwt-secret` | SecureString | `setup-ssm-params.sh` | ✅ |
| `jwt-refresh-secret` | SecureString | `setup-ssm-params.sh` | ✅ |
| `openai-api-key` | SecureString | `setup-ssm-params.sh` | ✅ |
| `stripe-secret-key` | SecureString | `setup-ssm-params.sh` | ✅ |
| `stripe-webhook-secret` | SecureString | `setup-ssm-params.sh` / Step 11 | ✅ |
| `stripe-price-id` | SecureString | `setup-ssm-params.sh` / Step 5 | ✅ |
| `ses-sender-email` | SecureString | `setup-ssm-params.sh` | ✅ |
| `kafka-bootstrap-servers` | SecureString | Step 7a (after CDK deploy) | ✅ |
| `api-url` | String | Step 7b (after CDK deploy) | ✅ |
| `domain-name` | SecureString | `setup-ssm-params.sh` | _(optional)_ |

#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# setup-ssm-params.sh
#
# Creates all SSM Parameter Store secrets required by the PFA backend before
# the first AWS CDK deployment. Run this once per stage (dev / prod).
#
# Prerequisites:
#   - AWS CLI configured (aws configure OR AWS_PROFILE set)
#   - Sufficient IAM permissions: ssm:PutParameter on /pfa/*
#
# Usage:
#   chmod +x infrastructure/scripts/setup-ssm-params.sh
#   ./infrastructure/scripts/setup-ssm-params.sh          # prompts for stage (default: dev)
#   STAGE=prod ./infrastructure/scripts/setup-ssm-params.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

STAGE="${STAGE:-}"
REGION="${AWS_REGION:-us-east-1}"

# ── Helpers ─────────────────────────────────────────────────────────────────
red()    { echo -e "\033[0;31m$*\033[0m"; }
green()  { echo -e "\033[0;32m$*\033[0m"; }
yellow() { echo -e "\033[0;33m$*\033[0m"; }
bold()   { echo -e "\033[1m$*\033[0m"; }

prompt_secret() {
  local name="$1" description="$2" default_hint="$3"
  local value=""
  echo ""
  bold "  $description"
  if [[ -n "$default_hint" ]]; then
    yellow "  Hint: $default_hint"
  fi
  while [[ -z "$value" ]]; do
    read -r -s -p "  Value (hidden): " value
    echo ""
    if [[ -z "$value" ]]; then
      red "  Value cannot be empty. Please try again."
    fi
  done
  echo "$value"
}

put_param() {
  local name="$1" value="$2" description="$3"
  aws ssm put-parameter \
    --name "/pfa/${STAGE}/${name}" \
    --value "$value" \
    --type "SecureString" \
    --description "$description" \
    --overwrite \
    --region "$REGION" \
    --output text --query "Version" > /dev/null
  green "  ✓ /pfa/${STAGE}/${name}"
}

# ── Stage selection ──────────────────────────────────────────────────────────
echo ""
bold "═══════════════════════════════════════════════════════"
bold "  PFA SSM Parameter Setup"
bold "═══════════════════════════════════════════════════════"
echo ""

if [[ -z "$STAGE" ]]; then
  read -r -p "  Deployment stage [dev/staging/prod] (default: dev): " STAGE
  STAGE="${STAGE:-dev}"
fi
echo "  Stage: $STAGE   Region: $REGION"
echo ""

# ── Confirm ──────────────────────────────────────────────────────────────────
read -r -p "  This will write SecureString parameters under /pfa/${STAGE}/. Continue? [y/N] " confirm
if [[ "${confirm,,}" != "y" ]]; then
  echo "Aborted."
  exit 0
fi

# ── JWT secrets ───────────────────────────────────────────────────────────────
bold ""
bold "── JWT Secrets ─────────────────────────────────────────"
JWT_SECRET=$(prompt_secret "jwt-secret" "JWT access token secret (min 32 chars)" \
  "Generate with: python3 -c \"import secrets; print(secrets.token_hex(32))\"")
put_param "jwt-secret" "$JWT_SECRET" "JWT access token signing key"

JWT_REFRESH=$(prompt_secret "jwt-refresh-secret" "JWT refresh token secret (different from above, min 32 chars)" \
  "Generate with: python3 -c \"import secrets; print(secrets.token_hex(32))\"")
put_param "jwt-refresh-secret" "$JWT_REFRESH" "JWT refresh token signing key"

# ── OpenAI ────────────────────────────────────────────────────────────────────
bold ""
bold "── OpenAI ──────────────────────────────────────────────"
OPENAI_KEY=$(prompt_secret "openai-api-key" "OpenAI API key" \
  "Get from: https://platform.openai.com/api-keys")
put_param "openai-api-key" "$OPENAI_KEY" "OpenAI API key for AI categorization"

# ── Stripe ────────────────────────────────────────────────────────────────────
bold ""
bold "── Stripe ──────────────────────────────────────────────"
STRIPE_SK=$(prompt_secret "stripe-secret-key" "Stripe secret key" \
  "Get from: https://dashboard.stripe.com/apikeys  (use sk_live_* for prod, sk_test_* for dev)")
put_param "stripe-secret-key" "$STRIPE_SK" "Stripe secret key"

STRIPE_WH=$(prompt_secret "stripe-webhook-secret" "Stripe webhook signing secret" \
  "Get from: https://dashboard.stripe.com/webhooks  (whsec_*)")
put_param "stripe-webhook-secret" "$STRIPE_WH" "Stripe webhook endpoint signing secret"

STRIPE_PRICE=$(prompt_secret "stripe-price-id" "Stripe Premium price ID" \
  "Get from: https://dashboard.stripe.com/products  (price_*)")
put_param "stripe-price-id" "$STRIPE_PRICE" "Stripe Premium monthly price ID"

# ── SES ───────────────────────────────────────────────────────────────────────
bold ""
bold "── SES Email ───────────────────────────────────────────"
yellow "  Ensure this email is verified in AWS SES before deploying."
read -r -p "  SES sender email address: " SES_EMAIL
SES_EMAIL="${SES_EMAIL:-noreply@example.com}"
put_param "ses-sender-email" "$SES_EMAIL" "SES verified sender email address"

# ── Domain (optional) ─────────────────────────────────────────────────────────
bold ""
bold "── Custom Domain (optional) ────────────────────────────"
read -r -p "  Custom domain name (leave blank to use CloudFront URL): " DOMAIN_NAME
DOMAIN_NAME="${DOMAIN_NAME:-}"
if [[ -n "$DOMAIN_NAME" ]]; then
  put_param "domain-name" "$DOMAIN_NAME" "Custom domain name for CloudFront"
else
  yellow "  Skipped — app will be accessible at the CloudFront *.cloudfront.net URL."
fi

# ── Kafka bootstrap servers (set after CDK deploy) ────────────────────────────
bold ""
bold "── Kafka Bootstrap Servers ────────────────────────────"
yellow "  NOTE: MSK is created by CDK. You can set this NOW with a placeholder"
yellow "  and update it after CDK deploy outputs the real broker string."
echo ""
read -r -p "  Kafka bootstrap servers [Enter to skip and set later]: " KAFKA_SERVERS
if [[ -n "$KAFKA_SERVERS" ]]; then
  put_param "kafka-bootstrap-servers" "$KAFKA_SERVERS" "MSK TLS bootstrap broker string"
else
  yellow "  ⚠  Set after CDK deploy — see docs/aws-deploy.md Step 7a."
fi

# ── API URL (set after CDK deploy — used by frontend CI build) ────────────────
bold ""
bold "── API / App URL ───────────────────────────────────────"
yellow "  NOTE: This is the CloudFront URL (or custom domain) used by the"
yellow "  frontend CI build to set NEXT_PUBLIC_API_URL."
yellow "  Skip for now and set it after CDK deploy outputs the CloudFront domain."
echo ""
read -r -p "  API URL (e.g. https://d1234.cloudfront.net) [Enter to skip]: " API_URL
if [[ -n "$API_URL" ]]; then
  # api-url is a plain String (not SecureString) — it's embedded in the JS bundle
  aws ssm put-parameter \
    --name "/pfa/${STAGE}/api-url" \
    --value "$API_URL" \
    --type "String" \
    --description "Frontend API base URL embedded in Next.js build" \
    --overwrite \
    --region "$REGION" \
    --output text --query "Version" > /dev/null
  green "  ✓ /pfa/${STAGE}/api-url"
else
  yellow "  ⚠  Set after CDK deploy — see docs/aws-deploy.md Step 7b."
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
bold "═══════════════════════════════════════════════════════"
green "  ✓ SSM parameters written for stage: ${STAGE}"
bold "═══════════════════════════════════════════════════════"
echo ""
echo "  Verify with:"
echo "    aws ssm get-parameters-by-path --path /pfa/${STAGE} --with-decryption \\"
echo "      --query 'Parameters[].{Name:Name,Value:Value}'"
echo ""
echo "  Next steps:"
echo "    1. cd infrastructure"
echo "    2. npx cdk bootstrap aws://\$(aws sts get-caller-identity --query Account --output text)/${REGION} --context stage=${STAGE}"
echo "    3. npx cdk deploy --all --context stage=${STAGE}"
echo "    4. After deploy: update kafka-bootstrap-servers and api-url (Step 7 in docs/aws-deploy.md)"
echo "    5. Push to main branch to trigger GitHub Actions CI/CD"
echo ""

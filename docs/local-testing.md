# Local Development & Testing Guide

Complete step-by-step guide to spin up every service locally and exercise the
full application — from registering a user through uploading a CSV, AI
categorization, anomaly detection, budget predictions, and Stripe billing.

---

## Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Docker Desktop | 4.x+ | `docker --version` |
| Docker Compose | v2 (bundled with Desktop) | `docker compose version` |
| Python | 3.12+ | `python --version` (for running tests locally) |
| Node.js | 20+ | `node --version` (optional — only if running frontend outside Docker) |

> **Windows users:** Enable WSL 2 backend in Docker Desktop settings.

---

## Step 1 — Configure `.env`

The `.env` file at the project root is already created with pre-generated JWT
secrets. You only need to fill in the keys for the services you want to test:

```bash
# Open with any editor
code .env          # VS Code
notepad .env       # Windows
```

### Minimum config for auth + transactions (no cloud services)

The following placeholders already in `.env` are **enough to start** — AI
categorization will fall back to keyword rules, S3 uploads will fail gracefully,
and email/Stripe features will be disabled:

```env
OPENAI_API_KEY=sk-placeholder        # AI uses keyword fallback — ok for basic testing
AWS_ACCESS_KEY_ID=                   # leave blank — presigned URL generation will fail
AWS_SECRET_ACCESS_KEY=               # leave blank
STRIPE_SECRET_KEY=sk_test_placeholder
STRIPE_WEBHOOK_SECRET=whsec_placeholder
STRIPE_PREMIUM_PRICE_ID=price_placeholder
SES_SENDER_EMAIL=noreply@example.com
```

### To enable full features, fill in real values

```env
OPENAI_API_KEY=sk-...                # https://platform.openai.com/api-keys
AWS_ACCESS_KEY_ID=AKIA...            # IAM user with S3 read/write on pfa-* buckets
AWS_SECRET_ACCESS_KEY=...
STRIPE_SECRET_KEY=sk_test_...        # https://dashboard.stripe.com/test/apikeys
STRIPE_WEBHOOK_SECRET=whsec_...      # see Step 7 (Stripe webhooks)
STRIPE_PREMIUM_PRICE_ID=price_...    # create in Stripe dashboard → Products
SES_SENDER_EMAIL=you@yourdomain.com  # must be SES-verified
```

---

## Step 2 — Build and Start All Services

```bash
# From the project root:
docker compose up --build -d
```

This builds the backend and frontend Docker images, then starts 5 containers:

| Container | Port | Purpose |
|-----------|------|---------|
| `pfa_postgres` | 5432 | PostgreSQL 16 database |
| `pfa_kafka` | 9092 (ext), 29092 (int) | Kafka broker (KRaft, no Zookeeper) |
| `pfa_kafka_ui` | 8080 | Kafka topic browser |
| `pfa_backend` | 8000 | FastAPI + Kafka workers (hot-reload) |
| `pfa_frontend` | 3000 | Next.js dev server (hot-reload) |

Wait ~30 seconds for Kafka to finish its first-time setup. Watch progress:

```bash
docker compose logs -f kafka       # wait for "Kafka Server started"
docker compose logs -f backend     # wait for "Application startup complete"
```

### Check all containers are healthy

```bash
docker compose ps
```

All services should show `healthy` or `running`. If `pfa_backend` is
restarting, check logs: `docker compose logs backend`.

---

## Step 3 — Run Database Migrations

Run this **once** after first startup (and again any time you add a new
migration):

```bash
docker compose exec backend python -m alembic upgrade head
```

Expected output:
```
INFO  [alembic.runtime.migration] Running upgrade  -> 001, Initial schema
```

Verify the 7 tables were created:

```bash
docker compose exec postgres psql -U pfa_user -d pfa_db -c "\dt"
```

Expected tables: `users`, `refresh_tokens`, `bank_statements`, `transactions`,
`budgets`, `savings_suggestions`, `monthly_reports`.

---

## Step 4 — Verify All Services

```bash
# 1. Backend health check
curl -s http://localhost:8000/health | python -m json.tool
# Expected: {"status": "ok", "environment": "development"}

# 2. API docs (open in browser)
open http://localhost:8000/docs          # macOS
start http://localhost:8000/docs         # Windows

# 3. Frontend (open in browser)
open http://localhost:3000               # macOS
start http://localhost:3000             # Windows

# 4. Kafka UI (topic browser)
open http://localhost:8080              # macOS
start http://localhost:8080            # Windows
```

---

## Step 5 — Test the Auth Flow (cURL)

### Register a new user

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "TestPass123!"}' \
  | python -m json.tool
```

Expected: `{"id": "...", "email": "test@example.com", "plan": "free", ...}`

### Login and capture the access token

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "TestPass123!"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

echo "Token: ${TOKEN:0:40}..."   # print first 40 chars as a sanity check
```

### Get current user profile

```bash
curl -s http://localhost:8000/api/v1/users/me \
  -H "Authorization: Bearer $TOKEN" \
  | python -m json.tool
```

---

## Step 6 — Upload a Test CSV

### Create a sample CSV

Save this as `/tmp/test_transactions.csv`:

```csv
Date,Description,Amount,Type
2024-01-05,STARBUCKS #12345,-4.75,debit
2024-01-06,NETFLIX.COM,-15.99,debit
2024-01-07,UBER TRIP HELP.UBER.COM,-12.50,debit
2024-01-10,WHOLE FOODS MARKET,-87.23,debit
2024-01-12,AMAZON.COM AMZN.COM,-63.40,debit
2024-01-15,PAYROLL DIRECT DEPOSIT,3500.00,credit
2024-01-16,PLANET FITNESS,-24.99,debit
2024-01-18,CHEVRON GAS STATION,-58.20,debit
2024-01-20,CVS PHARMACY,-18.75,debit
2024-01-22,SPOTIFY USA,-9.99,debit
2024-01-25,CHIPOTLE MEXICAN GRILL,-13.85,debit
2024-01-28,ELECTRIC BILL PAYMENT,-95.00,debit
2024-01-30,STARBUCKS #99887,-5.25,debit
2024-02-01,NETFLIX.COM,-15.99,debit
2024-02-03,UBER TRIP HELP.UBER.COM,-9.75,debit
2024-02-08,TRADER JOE'S,-124.67,debit
2024-02-15,PAYROLL DIRECT DEPOSIT,3500.00,credit
2024-02-16,PLANET FITNESS,-24.99,debit
2024-02-19,STARBUCKS #12345,-6.10,debit
2024-02-22,AMAZON.COM AMZN.COM,-156.89,debit
2024-02-25,AT&T BILL PAYMENT,-78.00,debit
2024-02-28,CHIPOTLE MEXICAN GRILL,-11.50,debit
```

### Request a presigned upload URL

> **Note:** This requires real AWS credentials in `.env`. Without them, skip
> to the direct API test in Step 6b.

```bash
UPLOAD_RESPONSE=$(curl -s -X POST http://localhost:8000/api/v1/statements/upload \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"file_type": "csv", "filename": "test_transactions.csv"}')

echo "$UPLOAD_RESPONSE" | python -m json.tool

# Extract values
STATEMENT_ID=$(echo "$UPLOAD_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin)['statement_id'])")
UPLOAD_URL=$(echo "$UPLOAD_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin)['upload_url'])")

# Upload directly to S3
curl -s -X PUT "$UPLOAD_URL" \
  -H "Content-Type: text/csv" \
  --data-binary @/tmp/test_transactions.csv
```

### Poll statement status until `completed`

```bash
watch -n 2 "curl -s http://localhost:8000/api/v1/statements/$STATEMENT_ID \
  -H 'Authorization: Bearer $TOKEN' | python -m json.tool"
```

Status flow: `pending` → `processing` → `completed`

### Step 6b — Test without S3 (no AWS credentials)

If you don't have AWS credentials, test the transaction and analytics endpoints
directly by seeding data via the Python shell:

```bash
docker compose exec backend python3 -c "
import asyncio
from app.database import get_engine
from app.models import Transaction, User
# use alembic-seeded data or test fixtures
print('Shell ready — import and seed as needed')
"
```

---

## Step 7 — View Transactions and Dashboard

```bash
# List all transactions
curl -s "http://localhost:8000/api/v1/transactions/" \
  -H "Authorization: Bearer $TOKEN" \
  | python -m json.tool

# Spending summary by category
curl -s "http://localhost:8000/api/v1/dashboard/spending-by-category" \
  -H "Authorization: Bearer $TOKEN" \
  | python -m json.tool

# Monthly trend (last 6 months)
curl -s "http://localhost:8000/api/v1/dashboard/spending-trend" \
  -H "Authorization: Bearer $TOKEN" \
  | python -m json.tool

# Dashboard overview (health score, income, expenses)
curl -s "http://localhost:8000/api/v1/dashboard/overview" \
  -H "Authorization: Bearer $TOKEN" \
  | python -m json.tool

# Anomalies detected
curl -s "http://localhost:8000/api/v1/transactions/anomalies" \
  -H "Authorization: Bearer $TOKEN" \
  | python -m json.tool
```

---

## Step 8 — Test Kafka Pipeline (Kafka UI)

Open **http://localhost:8080** in your browser.

After uploading a CSV you should see messages in these topics:

| Topic | When | Message count |
|-------|------|--------------|
| `statement.uploaded` | After POST /statements/upload | 1 per upload |
| `statement.parsed` | After parser worker runs | 1 per upload |
| `transactions.categorized` | After AI categorizer runs | 1 per upload |
| `anomalies.detected` | After anomaly detector runs | 1 per upload |

If a topic shows **0 messages**, check the backend logs:

```bash
docker compose logs -f backend | grep -E "ERROR|worker|kafka"
```

---

## Step 9 — Test Stripe Billing (test mode)

### Install Stripe CLI

```bash
# macOS
brew install stripe/stripe-cli/stripe

# Windows (scoop)
scoop bucket add stripe https://github.com/stripe/scoop-stripe-cli.git
scoop install stripe
```

### Login and forward webhooks

```bash
stripe login
stripe listen --forward-to http://localhost:8000/api/v1/billing/webhook
```

Copy the `whsec_...` secret printed by `stripe listen` into your `.env`:
```env
STRIPE_WEBHOOK_SECRET=whsec_...
```

Then restart the backend: `docker compose restart backend`

### Simulate a checkout

```bash
# Get checkout URL
CHECKOUT=$(curl -s -X POST http://localhost:8000/api/v1/billing/checkout \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  | python -m json.tool)

echo "$CHECKOUT"   # open the URL in your browser
```

### Trigger a test payment event

```bash
stripe trigger checkout.session.completed
```

Verify plan upgraded:

```bash
curl -s http://localhost:8000/api/v1/users/me \
  -H "Authorization: Bearer $TOKEN" \
  | python -c "import sys,json; d=json.load(sys.stdin); print('Plan:', d['plan'])"
# Expected: Plan: premium
```

---

## Step 10 — Run the Full Test Suite

```bash
# From project root — runs all 165 tests with coverage
cd backend
pip install -e ".[dev]" --quiet    # only needed first time outside Docker
python -m pytest -v --cov=app --cov-report=term-missing
```

Or inside Docker (matches CI exactly):

```bash
docker compose exec backend python -m pytest -v --cov=app
```

Expected: **165 passed** in ~25 seconds, 69% coverage.

---

## Useful Development Commands

```bash
# === Docker Compose ===
docker compose up -d                     # start all (detached)
docker compose up -d --build backend     # rebuild and restart just the backend
docker compose restart backend           # restart without rebuild (picks up .env changes)
docker compose logs -f backend           # tail backend logs
docker compose logs -f --since=5m        # last 5 minutes, all services
docker compose down                      # stop all (keep volumes)
docker compose down -v                   # stop all AND wipe database volume

# === Database ===
docker compose exec backend python -m alembic upgrade head    # run migrations
docker compose exec backend python -m alembic current         # show current revision
docker compose exec backend python -m alembic history         # show migration history
docker compose exec postgres psql -U pfa_user -d pfa_db       # psql shell
docker compose exec postgres psql -U pfa_user -d pfa_db \
  -c "SELECT id, email, plan FROM users"                      # quick user query

# === Backend (inside container) ===
docker compose exec backend python -m alembic downgrade -1    # rollback one migration
docker compose exec backend python -m pytest tests/test_auth.py -v   # run one test file

# === Kafka ===
# List topics
docker compose exec kafka kafka-topics \
  --bootstrap-server localhost:9092 --list

# Consume messages from a topic (press Ctrl+C to stop)
docker compose exec kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic statement.uploaded \
  --from-beginning

# === Cleanup ===
docker compose down --rmi local -v       # full clean: stop, remove images + volumes
```

---

## Troubleshooting

### Backend won't start — `connection refused` to Postgres/Kafka

The backend starts as soon as dependencies report healthy. If it's still failing:

```bash
docker compose ps          # check which services are unhealthy
docker compose logs kafka  # look for "Kafka Server started"
```

If Kafka health check keeps failing, wipe the volume and restart:

```bash
docker compose down -v && docker compose up -d
```

### `ModuleNotFoundError` in backend

The backend volume-mounts `./backend:/app`. If you added a new Python package:

```bash
docker compose up -d --build backend
```

### Frontend shows blank page / API 404s

Check that `NEXT_PUBLIC_API_URL=http://localhost:8000` is in `.env` and
the backend is running on port 8000: `curl http://localhost:8000/health`

### Alembic `Target database is not up to date`

```bash
docker compose exec backend python -m alembic upgrade head
```

### AI categorization not working

Check the OpenAI key in `.env`. If `OPENAI_API_KEY=sk-placeholder`, the
system falls back to keyword-based categorization — transactions will still
get categories like "Food & Dining", "Subscriptions", etc., just not AI-powered.

### Kafka messages not processing

```bash
docker compose logs backend | grep -i "kafka\|worker\|consumer"
```

Workers are embedded in the backend process. If Kafka is healthy but messages
aren't processing, restart the backend:

```bash
docker compose restart backend
```

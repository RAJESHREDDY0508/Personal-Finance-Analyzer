# AI Personal Finance Analyzer — Full Project Plan

## Context

Starting from a blank git repository. The goal is to build a production-ready AI-powered SaaS platform that lets users upload bank statements, automatically categorizes transactions using OpenAI, detects anomalies, forecasts budgets with ML, and provides actionable savings insights.

**Confirmed Stack:**
- Frontend: Next.js 14 (App Router) + Tailwind CSS + shadcn/ui + Recharts
- Backend: FastAPI (Python 3.12) + Alembic migrations
- Auth: JWT (access + refresh tokens, custom FastAPI)
- AI: OpenAI GPT-4o (categorization + anomaly explanation) + scikit-learn (ML predictions)
- Database: PostgreSQL (Docker locally → AWS RDS in prod)
- Event Streaming: Apache Kafka (Docker locally → AWS MSK in prod)
- File Storage: AWS S3
- Email: AWS SES
- Payments: Stripe
- Deployment: AWS (EC2, RDS, MSK, S3, ALB, CloudFront, Route 53, ACM, CloudWatch)
- CI/CD: GitHub Actions

---

## Monorepo Structure

```
/
├── backend/                  FastAPI Python app
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py         Pydantic Settings
│   │   ├── database.py       AsyncEngine + get_db
│   │   ├── models/           SQLAlchemy ORM
│   │   ├── schemas/          Pydantic req/resp
│   │   ├── api/v1/           FastAPI routers
│   │   ├── services/         Business logic
│   │   ├── workers/          Kafka consumers
│   │   ├── kafka/            Producer + topic constants
│   │   └── utils/            Parsers, JWT, S3, health score
│   ├── alembic/
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/                 Next.js app
│   └── src/
│       ├── app/              App Router pages
│       ├── components/       Reusable UI + charts
│       ├── lib/              API client, auth helpers
│       ├── hooks/            React Query hooks
│       └── stores/           Zustand global state
├── infrastructure/           AWS CDK (TypeScript)
├── docker-compose.yml
├── .env.example
├── .gitignore
└── .github/workflows/        CI/CD
```

---

## Database Schema (7 tables)

| Table | Key Fields |
|---|---|
| `users` | id (UUID), email, password_hash, plan ('free'\|'premium'), health_score, stripe_customer_id |
| `refresh_tokens` | id, user_id→users, token_hash, expires_at, revoked |
| `bank_statements` | id, user_id→users, s3_key, file_type ('csv'\|'pdf'), status ('pending'\|'processing'\|'completed'\|'failed') |
| `transactions` | id, user_id, statement_id, date, description, amount, category, is_anomaly, anomaly_score, is_duplicate, categorization_source |
| `budgets` | id, user_id, category, month (DATE), monthly_limit, predicted_spend, ml_confidence |
| `savings_suggestions` | id, user_id, suggestion_type, category, description, estimated_savings, dismissed |
| `monthly_reports` | id, user_id, report_month, s3_key, email_sent, total_income, total_expenses, health_score |

---

## Kafka Topics (6 topics)

| Topic | Producer | Consumer | Purpose |
|---|---|---|---|
| `statement.uploaded` | FastAPI upload endpoint | statement-parser-worker | Trigger CSV/PDF parsing |
| `statement.parsed` | statement-parser-worker | ai-categorizer-worker | Trigger AI categorization |
| `transactions.categorized` | ai-categorizer-worker | anomaly-detector + ml-predictor | Trigger anomaly + prediction |
| `anomalies.detected` | anomaly-detector-worker | suggestion-engine-worker | Trigger savings suggestions |
| `report.schedule` | cron job | report-generator + email-sender | Monthly report pipeline |
| `subscription.events` | Stripe webhook handler | subscription-handler-worker | Plan upgrades/downgrades |

---

## API Endpoints Summary

```
/api/v1/auth          POST /register, /login, /refresh, /logout
/api/v1/users         GET|PATCH|DELETE /me
/api/v1/statements    POST /upload, GET /, GET /{id}, DELETE /{id}, POST /{id}/reprocess
/api/v1/transactions  GET /, GET /{id}, PATCH /{id}/category, GET /summary, /anomalies, /duplicates
/api/v1/budgets       GET /, POST /, GET /predictions, GET /vs-actual
/api/v1/dashboard     GET /overview, /spending-by-category, /spending-trend, /savings-rate
/api/v1/suggestions   GET /, POST /{id}/dismiss, POST /generate
/api/v1/reports       GET /, GET /{id}/download, POST /generate, POST /send-email
/api/v1/billing       GET /plans, POST /checkout, POST /portal, POST /webhook, GET /subscription
```

---

## AWS Architecture

```
Internet → Route 53 → ACM (TLS)
         → CloudFront
               ├── /api/* → ALB → EC2 Auto Scaling Group (FastAPI + Kafka workers)
               └── /*     → S3 (Next.js static) OR ALB → EC2 (Next.js SSR)

Private Subnet:
  - RDS PostgreSQL (Multi-AZ)
  - MSK (3 Kafka brokers, m5.large)

S3 Buckets:
  - pfa-statements-{env}   (private, signed URLs)
  - pfa-reports-{env}      (private, signed URLs)
  - pfa-frontend-{env}     (public static assets)

Supporting:
  - Secrets Manager (DB creds, OpenAI key, Stripe keys, JWT secrets)
  - SES (email reports + password resets)
  - CloudWatch (logs, metrics, alarms)
  - GitHub Actions OIDC → IAM role for deployments
```

---

## Implementation Phases

### Phase 0 — Repository & Dev Environment (Days 1–3)
**Goal:** Working local dev environment, CI skeleton.

- [ ] Root `.gitignore`, `.env.example`, `README.md`
- [ ] `docker-compose.yml` — services: postgres:16, kafka (KRaft mode), kafka-ui, backend, frontend
- [ ] Backend scaffold: `pyproject.toml`, `Dockerfile`, `app/` directory tree (empty modules)
- [ ] Frontend scaffold: `create-next-app`, install shadcn/ui, recharts, react-query, zustand, zod, axios
- [ ] Alembic init (`alembic.ini`, async `env.py`)
- [ ] GitHub Actions: `ci.yml` (lint + test on PR), `deploy.yml` (deploy on main merge)
- [ ] Infrastructure skeleton: `/infrastructure/` with AWS CDK TypeScript project

**Verify:** `docker compose up` starts all services; frontend hits `localhost:3000`, FastAPI hits `localhost:8000/docs`.

---

### Phase 1 — Database Models & Auth (Days 4–8)
**Goal:** All 7 DB tables live; users can register, login, and get protected routes.

- [ ] SQLAlchemy async models for all 7 tables in `app/models/`
- [ ] Alembic initial migration (`001_initial_schema.py`)
- [ ] `app/utils/security.py`: bcrypt hashing, JWT encode/decode (access 15min, refresh 7 days)
- [ ] `app/services/auth_service.py`: register, login, refresh, logout logic
- [ ] `app/api/v1/auth.py` router: all 4 auth endpoints
- [ ] `app/api/deps.py`: `get_current_user`, `require_premium` dependencies
- [ ] `app/api/v1/users.py`: GET/PATCH/DELETE `/me`
- [ ] Pydantic schemas for auth + user in `app/schemas/`

**Verify:** Register → login → get `/me` with Bearer token → refresh → logout cycle works via Swagger UI.

---

### Phase 2 — File Upload & Statement Parsing (Days 9–13)
**Goal:** Users upload CSV/PDF; raw transactions stored in DB via Kafka pipeline.

- [ ] `app/utils/s3.py`: generate pre-signed upload URL, download object
- [ ] `app/api/v1/statements.py`: POST `/upload` → create DB record → produce to `statement.uploaded` → return pre-signed S3 URL
- [ ] `app/kafka/producer.py`: singleton AIOKafka producer with startup/shutdown lifecycle
- [ ] `app/utils/csv_parser.py`: detect and parse common CSV bank export formats (date, description, amount columns); handle comma/semicolon separators; normalize amounts
- [ ] `app/utils/pdf_parser.py`: extract transaction table from PDF using pdfplumber; regex-based row detection
- [ ] `app/workers/statement_parser.py`: consumes `statement.uploaded` → downloads S3 file → parses → bulk inserts raw transactions → updates statement status → produces to `statement.parsed`
- [ ] GET `/statements/` and GET `/statements/{id}` endpoints

**Verify:** Upload a sample CSV → statement status goes `pending → processing → completed` → transactions visible via GET `/transactions/`.

---

### Phase 3 — AI Transaction Categorization (Days 14–18)
**Goal:** Every parsed transaction gets a category assigned by OpenAI (with rule-based fallback).

- [ ] Category taxonomy constant (15 categories): Food & Dining, Groceries, Rent/Mortgage, Utilities, Transportation, Entertainment, Shopping, Subscriptions, Healthcare, Education, Travel, Personal Care, Savings/Investments, Income, Other
- [ ] `app/services/ai_service.py`: batch categorization using OpenAI GPT-4o with structured output (JSON mode); prompts transaction descriptions in batches of 50; sets `categorization_source = 'ai'`
- [ ] Rule-based fallback in same service: keyword-to-category map for common merchants (Starbucks→Food, Netflix→Subscriptions, Uber→Transportation, etc.)
- [ ] `app/workers/ai_categorizer.py`: consumes `statement.parsed` → fetches uncategorized transactions in bulk → calls `ai_service` → updates DB → produces to `transactions.categorized`
- [ ] PATCH `/transactions/{id}/category` endpoint (user override, sets `categorization_source = 'user'`)

**Verify:** Upload CSV → wait for pipeline → check `/transactions/` — each row has `category` populated and `categorization_source` set.

---

### Phase 4 — Analytics & Dashboard API (Days 19–23)
**Goal:** All dashboard data endpoints ready for frontend consumption.

- [ ] `app/services/analytics_service.py`:
  - `get_spending_by_category(user_id, month)` → sum per category
  - `get_monthly_trend(user_id, months=6)` → array of {month, total}
  - `get_savings_rate(user_id)` → (income - expenses) / income
  - `get_recurring_subscriptions(user_id)` → transactions matching same merchant monthly
  - `get_largest_expenses(user_id, month, limit=5)` → top N transactions
  - `get_health_score(user_id)` → 0–100 composite score
- [ ] `app/api/v1/dashboard.py`: 4 GET endpoints mapping to service methods
- [ ] `app/api/v1/transactions.py`: GET `/summary`, `/anomalies`, `/duplicates` with date range + category filters

**Verify:** After uploading multi-month CSV fixture, `/dashboard/spending-by-category` returns correct sums matching manual calculation.

---

### Phase 5 — Anomaly Detection (Days 24–28)
**Goal:** System auto-flags unusual transactions and duplicate charges.

- [ ] `app/services/anomaly_service.py`:
  - Z-score method: per-category rolling 3-month baseline; flag if z-score > 2.5
  - Duplicate detection: same merchant + same amount within 3 days of another transaction
  - Category spike: if monthly category total > 150% of 3-month average → flag
  - OpenAI explanation generation for each anomaly (human-readable reason text)
- [ ] `app/workers/anomaly_detector.py`: consumes `transactions.categorized` → runs all anomaly checks → updates `is_anomaly`, `anomaly_score`, `anomaly_reason` fields → produces to `anomalies.detected`
- [ ] GET `/transactions/anomalies` returns all flagged transactions with reason text
- [ ] GET `/transactions/duplicates` returns suspected duplicate pairs

**Verify:** Inject a test transaction 5x normal spending amount → confirm it appears in `/transactions/anomalies` with a reason string.

---

### Phase 6 — Budget Prediction & Savings Suggestions (Days 29–33)
**Goal:** ML forecasts next month's spending per category; AI generates savings suggestions.

- [ ] `app/services/ml_service.py`:
  - Uses scikit-learn LinearRegression + seasonal decomposition
  - Trains per user per category on available months of history (min 2 months)
  - Returns predicted spend + confidence interval
  - Falls back to 3-month moving average if < 2 months data
- [ ] `app/workers/ml_predictor.py`: consumes `transactions.categorized` → runs ML per category → upserts `budgets` table for next month
- [ ] `app/services/suggestion_service.py`:
  - Compares actual vs predicted spend; surfaces top 3 reduction opportunities
  - Detects subscriptions with no recent usage (anomaly score high + subscription category)
  - Calculates estimated_savings per suggestion
  - Uses OpenAI for human-readable suggestion text
- [ ] `app/workers/suggestion_engine.py`: consumes `anomalies.detected` → generates/updates suggestions in DB
- [ ] `app/utils/health_score.py`: composite score algorithm (savings rate 40%, expense stability 30%, income/expense ratio 30%)
- [ ] Budget endpoints: GET `/budgets/`, POST `/budgets/`, GET `/budgets/predictions`, GET `/budgets/vs-actual`
- [ ] Suggestion endpoints: GET `/suggestions/`, POST `/{id}/dismiss`, POST `/generate`

**Verify:** After 3+ months of data, `/budgets/predictions` returns category budgets; `/suggestions/` lists at least one actionable suggestion.

---

### Phase 7 — Frontend (Days 34–50)
**Goal:** Full Next.js UI connecting to all backend endpoints.

**Auth Pages** (`/login`, `/register`, `/forgot-password`):
- [ ] Forms with react-hook-form + zod validation
- [ ] JWT stored in httpOnly cookies via Next.js API route proxy
- [ ] Protected route middleware in `middleware.ts`
- [ ] Zustand auth store for client-side session

**Dashboard Page** (`/dashboard`):
- [ ] Health score card (large number + color ring)
- [ ] Spending pie chart (Recharts PieChart) ← `/dashboard/spending-by-category`
- [ ] Monthly trend line chart (Recharts LineChart) ← `/dashboard/spending-trend`
- [ ] Savings rate card ← `/dashboard/savings-rate`
- [ ] Top 5 expenses list
- [ ] Recurring subscriptions list

**Upload Page** (`/upload`):
- [ ] Drag-and-drop zone (react-dropzone)
- [ ] CSV + PDF file type validation
- [ ] Direct-to-S3 upload using pre-signed URL from backend
- [ ] Real-time status polling (React Query refetch interval) showing `pending → processing → completed`
- [ ] Statement history list with status badges

**Transactions Page** (`/transactions`):
- [ ] Searchable, filterable table (by category, date range, anomaly flag)
- [ ] Inline category override (click → dropdown → save)
- [ ] Anomaly badge with reason tooltip
- [ ] Pagination

**Alerts Page** (`/alerts`):
- [ ] Anomaly cards with transaction details + AI explanation
- [ ] Duplicate charge groupings
- [ ] Dismiss action

**Budget Page** (`/budget`):
- [ ] Budget vs actual bar charts per category
- [ ] ML prediction cards for next month
- [ ] Set custom budget limit per category
- [ ] Savings suggestions cards with dismiss button

**Settings Page** (`/settings`):
- [ ] Profile update form
- [ ] Email report toggle
- [ ] Subscription status + Stripe portal link
- [ ] Account deletion with confirmation

**Shared Components:**
- [ ] `Navbar` with user menu and logout
- [ ] `Sidebar` with navigation links
- [ ] `StatCard` for KPI metrics
- [ ] `LoadingSkeleton` for all data states
- [ ] `ErrorBoundary` with retry
- [ ] `ThemeToggle` (dark/light via next-themes)

**Verify:** Full user journey — register → upload CSV → view dashboard → check alerts → set budgets → view suggestions — works end to end in browser.

---

### Phase 8 — Monthly Email Reports (Days 51–54)
**Goal:** Users receive a formatted HTML email report on the 1st of each month.

- [ ] `app/services/report_service.py`: aggregate monthly data → build report dict (income, expenses, top category, health score, savings)
- [ ] HTML email template (Jinja2): styled table layout showing financial summary
- [ ] `app/services/email_service.py`: AWS SES `send_raw_email` with HTML body
- [ ] `app/workers/report_generator.py`: consumes `report.schedule` → calls report service → stores in `monthly_reports` table + uploads HTML to S3
- [ ] `app/workers/email_sender.py`: consumes `report.schedule` → sends via SES → marks `email_sent = true`
- [ ] Cron trigger: GitHub Actions scheduled workflow OR APScheduler in backend on the 1st of each month producing to `report.schedule` for all active users

**Verify:** Manually POST `/reports/generate` + `/reports/send-email` → email received with correct monthly figures.

---

### Phase 9 — SaaS Billing (Days 55–58)
**Goal:** Stripe checkout for Premium tier; feature gating enforced.

- [ ] Stripe product + price setup in dashboard (Premium $5/month recurring)
- [ ] `app/services/billing_service.py`: create checkout session, create billing portal session, handle webhook events
- [ ] POST `/billing/checkout` → returns Stripe checkout URL
- [ ] POST `/billing/portal` → returns Stripe billing portal URL
- [ ] POST `/billing/webhook` → verify Stripe signature → update `users.plan` field → produce to `subscription.events`
- [ ] `require_premium` FastAPI dependency: checks `current_user.plan == 'premium'`; raises 402 if free
- [ ] Gate the following behind premium: `/suggestions/`, `/budgets/predictions`, `/dashboard/spending-trend`, anomaly alerts
- [ ] Frontend upgrade prompt component: shown when 402 received

**Verify:** Complete Stripe test checkout flow → plan updated to 'premium' in DB → previously gated features now accessible.

---

### Phase 10 — AWS Production Deployment (Days 59–70)
**Goal:** Platform running on AWS with proper networking, security, monitoring, CI/CD.

**Infrastructure (CDK in `/infrastructure/`):**
- [ ] VPC: 2 public subnets (ALB, NAT GW), 2 private subnets (EC2, RDS, MSK)
- [ ] RDS: PostgreSQL 16, db.t3.medium, Multi-AZ, private subnet, automated backups
- [ ] MSK: 3 brokers, kafka.m5.large, private subnet, TLS in-transit encryption
- [ ] S3: 3 buckets (statements, reports, frontend) with appropriate policies
- [ ] EC2 Launch Template + Auto Scaling Group (t3.medium, min 1, max 3)
- [ ] ALB: listeners on 80 (redirect to 443) and 443; target group → EC2
- [ ] CloudFront: origin = ALB for `/api/*`, origin = S3 for `/*`
- [ ] Route 53: A record pointing to CloudFront
- [ ] ACM: certificate for domain, validated via Route 53
- [ ] Secrets Manager: all secrets stored; EC2 instance role reads them on startup
- [ ] CloudWatch log groups: `/pfa/backend`, `/pfa/workers`; alarms on 5xx rate > 1%, latency p99 > 2s, Kafka consumer lag > 1000

**CI/CD (`.github/workflows/`):**
- [ ] `ci.yml`: on PR → run `ruff`, `mypy`, `pytest` for backend; `next build` for frontend
- [ ] `deploy-backend.yml`: on push to `main` → SSH to EC2 → git pull → restart uvicorn + workers via systemd
- [ ] `deploy-frontend.yml`: on push to `main` → `next build` → `aws s3 sync` to S3 bucket → CloudFront invalidation

**EC2 Setup Script:**
- [ ] `scripts/setup-ec2.sh`: installs Python 3.12, node 20, configures systemd units for `pfa-api` and `pfa-workers`

**Verify:** `git push main` → GitHub Actions deploy → production URL returns healthy response → CloudWatch shows logs flowing.

---

## Testing Strategy

| Phase | Test Type | Tool |
|---|---|---|
| Phase 1 | Unit tests for JWT encode/decode + password hashing | pytest |
| Phase 1 | Integration: register + login + refresh + logout flow | pytest + httpx TestClient |
| Phase 2 | Unit: CSV parser with 5 real-world bank export formats | pytest |
| Phase 2 | Unit: PDF parser with fixture PDFs | pytest |
| Phase 3 | Integration: mock OpenAI → verify categories assigned | pytest + respx |
| Phase 4 | Unit: analytics calculations with known fixture data | pytest |
| Phase 5 | Unit: Z-score anomaly logic with synthetic data | pytest |
| Phase 6 | Unit: ML predictor with 3-month fixture; assert predictions within 20% | pytest |
| Phase 7 | E2E: full user journey | Playwright |
| Phase 9 | Stripe webhook: test with Stripe CLI `stripe trigger` | manual |
| Phase 10 | Load test: 50 concurrent uploads | k6 |

---

## Key Dependencies Between Phases

```
Phase 0 (scaffold) → Phase 1 (DB + auth)
Phase 1            → Phase 2 (upload uses auth)
Phase 2            → Phase 3 (categorization reads parsed transactions)
Phase 3            → Phase 4 (analytics reads categorized transactions)
Phase 3            → Phase 5 (anomaly detection needs categories)
Phase 5            → Phase 6 (suggestions use anomaly results)
Phase 4 + 5 + 6    → Phase 7 (frontend consumes all APIs)
Phase 7            → Phase 8 (reports use same data as dashboard)
Phase 1 + 7        → Phase 9 (billing wraps auth + UI)
All phases         → Phase 10 (deployment)
```

---

## Critical Files (first to create)

1. `docker-compose.yml` — gates all local dev
2. `backend/pyproject.toml` — gates all Python work
3. `backend/app/config.py` — gates all service config
4. `backend/app/database.py` — gates all DB work
5. `backend/alembic/versions/001_initial_schema.py` — gates all data work
6. `backend/app/utils/security.py` — gates auth
7. `frontend/src/lib/api.ts` — gates all frontend API calls
8. `frontend/src/middleware.ts` — gates route protection

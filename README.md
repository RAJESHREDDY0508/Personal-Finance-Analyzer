# AI Personal Finance Analyzer

> An AI-powered SaaS platform that automatically analyzes bank statements, categorizes transactions, detects anomalies, forecasts budgets, and provides actionable savings insights.

---

## Architecture Overview

```
Internet → Route 53 → CloudFront
                ├── /api/* → ALB → EC2 (FastAPI + Kafka Workers)
                └── /*     → S3  (Next.js Static)

Private Subnet:
  ├── RDS PostgreSQL (Multi-AZ)
  └── MSK Kafka (3 brokers)

Supporting Services:
  ├── S3        — bank statement + report storage
  ├── SES       — monthly email reports
  ├── Stripe    — subscription billing
  └── CloudWatch — logs + metrics + alarms
```

## Kafka Pipeline

```
Upload Statement
    ↓  [statement.uploaded]
Statement Parser Worker  (CSV / PDF → raw transactions)
    ↓  [statement.parsed]
AI Categorizer Worker    (OpenAI GPT-4o → categories)
    ↓  [transactions.categorized]
Anomaly Detector         (Z-score + duplicates)
ML Predictor             (scikit-learn → budget forecast)
    ↓  [anomalies.detected]
Suggestion Engine        (savings recommendations)
```

---

## Tech Stack

| Layer     | Technology                                                 |
| --------- | ---------------------------------------------------------- |
| Frontend  | Next.js 14 (App Router), Tailwind CSS, shadcn/ui, Recharts |
| Backend   | FastAPI (Python 3.12), Alembic                             |
| Auth      | JWT (custom — access 15 min + refresh 7 days)             |
| AI        | OpenAI GPT-4o + scikit-learn                               |
| Database  | PostgreSQL 16                                              |
| Streaming | Apache Kafka (KRaft)                                       |
| Storage   | AWS S3                                                     |
| Email     | AWS SES                                                    |
| Payments  | Stripe                                                     |
| Infra     | AWS via CDK (TypeScript)                                   |
| CI/CD     | GitHub Actions                                             |

---

## Local Development Setup

### Prerequisites

- Docker Desktop
- Node.js 20+
- Python 3.12+

### 1. Clone & configure environment

```bash
git clone <repo-url>
cd "AI Personal Finance Analyzer"
cp .env.example .env
# Edit .env with your OpenAI key, Stripe keys, AWS keys
```

### 2. Start all services

```bash
docker compose up --build
```

| Service           | URL                        |
| ----------------- | -------------------------- |
| FastAPI (Swagger) | http://localhost:8000/docs |
| Next.js Frontend  | http://localhost:3000      |
| Kafka UI          | http://localhost:8080      |
| PostgreSQL        | localhost:5432             |

### 3. Run database migrations

```bash
cd backend
alembic upgrade head
```

### 4. Run tests

```bash
# Backend
cd backend
pytest

# Frontend
cd frontend
npm run test
```

---

## Project Structure

```
/
├── backend/                  FastAPI Python app
│   ├── app/
│   │   ├── main.py           App factory + lifespan
│   │   ├── config.py         Pydantic Settings
│   │   ├── database.py       Async SQLAlchemy engine
│   │   ├── models/           ORM models (7 tables)
│   │   ├── schemas/          Pydantic request/response
│   │   ├── api/v1/           REST API routers
│   │   ├── services/         Business logic layer
│   │   ├── workers/          Kafka consumer workers
│   │   ├── kafka/            Producer + topic constants
│   │   └── utils/            JWT, S3, parsers, health score
│   ├── alembic/              DB migrations
│   ├── tests/
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/                 Next.js app
│   └── src/
│       ├── app/              App Router pages
│       ├── components/       UI components + charts
│       ├── lib/              API client + helpers
│       ├── hooks/            React Query hooks
│       └── stores/           Zustand global state
├── infrastructure/           AWS CDK stacks
├── docker-compose.yml
├── .env.example
└── PLAN.md                   Full project roadmap
```

---

## API Endpoints

```
/api/v1/auth          POST /register, /login, /refresh, /logout
/api/v1/users         GET|PATCH|DELETE /me
/api/v1/statements    POST /upload, GET /, GET /{id}, DELETE /{id}
/api/v1/transactions  GET /, GET /{id}, PATCH /{id}/category
/api/v1/dashboard     GET /overview, /spending-by-category, /spending-trend
/api/v1/budgets       GET /, POST /, GET /predictions, GET /vs-actual
/api/v1/suggestions   GET /, POST /{id}/dismiss
/api/v1/reports       GET /, GET /{id}/download
/api/v1/billing       POST /checkout, POST /portal, POST /webhook
```

---

## SaaS Pricing

| Tier    | Price | Features                                                                                 |
| ------- | ----- | ---------------------------------------------------------------------------------------- |
| Free    | $0    | Upload statements, basic categorization, dashboard, monthly reports                      |
| Premium | $5/mo | AI insights, anomaly alerts, budget predictions, savings suggestions, advanced analytics |

---

## Deployment

Production is deployed to AWS via CDK. See `/infrastructure/` for stacks.

```bash
cd infrastructure
npm install
npx cdk deploy --all
```

CI/CD runs on every push to `main` via GitHub Actions.

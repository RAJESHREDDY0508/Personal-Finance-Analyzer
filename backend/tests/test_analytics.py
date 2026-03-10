"""
Tests for analytics dashboard endpoints and anomaly detection.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_auth import REGISTER_PAYLOAD
from app.models.transaction import Transaction
from app.services.anomaly_service import detect_duplicates, detect_zscore_anomalies
from app.utils.health_score import compute_health_score


# ── Helpers ───────────────────────────────────────────────────

async def _auth_headers(client: AsyncClient) -> dict:
    resp = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _seed_transactions(db_session: AsyncSession, user_id: uuid.UUID) -> uuid.UUID:
    """Insert sample transactions for analytics tests."""
    stmt_id = uuid.uuid4()
    today = date.today()
    transactions = [
        Transaction(
            user_id=user_id, statement_id=stmt_id, date=today,
            description="SALARY", amount=Decimal("3000"), is_income=True, category="Income",
        ),
        Transaction(
            user_id=user_id, statement_id=stmt_id, date=today,
            description="RENT", amount=Decimal("-1200"), is_income=False, category="Housing",
        ),
        Transaction(
            user_id=user_id, statement_id=stmt_id, date=today,
            description="WHOLE FOODS", amount=Decimal("-200"), is_income=False, category="Groceries",
        ),
        Transaction(
            user_id=user_id, statement_id=stmt_id, date=today,
            description="NETFLIX", amount=Decimal("-15"), is_income=False, category="Entertainment",
        ),
        Transaction(
            user_id=user_id, statement_id=stmt_id, date=today,
            description="GAS", amount=Decimal("-60"), is_income=False, category="Transportation",
        ),
    ]
    db_session.add_all(transactions)
    await db_session.commit()
    return stmt_id


# ── Health score unit tests ───────────────────────────────────

def test_health_score_perfect_saver():
    score = compute_health_score(
        income=5000, expenses=1000, category_count=8,
        anomaly_count=0, total_transactions=20,
    )
    assert score >= 75


def test_health_score_poor_saver():
    score = compute_health_score(
        income=3000, expenses=3500, category_count=3,
        anomaly_count=0, total_transactions=20,
    )
    assert score < 30


def test_health_score_no_income():
    score = compute_health_score(
        income=0, expenses=500, category_count=2,
        anomaly_count=0, total_transactions=5,
    )
    assert score == 0


def test_health_score_anomaly_penalty():
    clean = compute_health_score(
        income=3000, expenses=1500, category_count=6,
        anomaly_count=0, total_transactions=50,
    )
    anomalous = compute_health_score(
        income=3000, expenses=1500, category_count=6,
        anomaly_count=10, total_transactions=50,
    )
    assert clean > anomalous


def test_health_score_in_range():
    score = compute_health_score(
        income=4000, expenses=2000, category_count=5,
        anomaly_count=2, total_transactions=30,
    )
    assert 0 <= score <= 100


# ── Anomaly detection unit tests ──────────────────────────────

@pytest.mark.asyncio
async def test_detect_duplicates_flags_same_txn(db_session: AsyncSession) -> None:
    from app.models.user import User
    from app.utils.security import hash_password
    user = User(email="dup@test.com", password_hash=hash_password("pass123"))
    db_session.add(user)
    await db_session.flush()

    stmt_a = uuid.uuid4()
    stmt_b = uuid.uuid4()
    txn1 = Transaction(
        user_id=user.id, statement_id=stmt_a, date=date(2025, 1, 1),
        description="DUPLICATE TXN", amount=Decimal("-50"), is_income=False,
    )
    db_session.add(txn1)
    await db_session.flush()

    txn2 = Transaction(
        user_id=user.id, statement_id=stmt_b, date=date(2025, 1, 1),
        description="DUPLICATE TXN", amount=Decimal("-50"), is_income=False,
    )
    db_session.add(txn2)
    await db_session.flush()

    flagged = await detect_duplicates(db_session, user.id, stmt_b)
    assert flagged == 1
    await db_session.refresh(txn2)
    assert txn2.is_duplicate is True
    assert txn2.duplicate_of == txn1.id


@pytest.mark.asyncio
async def test_detect_duplicates_different_amounts_not_flagged(db_session: AsyncSession) -> None:
    from app.models.user import User
    from app.utils.security import hash_password
    user = User(email="nodup@test.com", password_hash=hash_password("pass123"))
    db_session.add(user)
    await db_session.flush()

    stmt_a, stmt_b = uuid.uuid4(), uuid.uuid4()
    txn1 = Transaction(
        user_id=user.id, statement_id=stmt_a, date=date(2025, 1, 1),
        description="GROCERY STORE", amount=Decimal("-50"), is_income=False,
    )
    txn2 = Transaction(
        user_id=user.id, statement_id=stmt_b, date=date(2025, 1, 1),
        description="GROCERY STORE", amount=Decimal("-55"), is_income=False,
    )
    db_session.add_all([txn1, txn2])
    await db_session.flush()

    flagged = await detect_duplicates(db_session, user.id, stmt_b)
    assert flagged == 0


@pytest.mark.asyncio
async def test_detect_zscore_insufficient_history(db_session: AsyncSession) -> None:
    from app.models.user import User
    from app.utils.security import hash_password
    user = User(email="zscore@test.com", password_hash=hash_password("pass123"))
    db_session.add(user)
    await db_session.flush()

    stmt_id = uuid.uuid4()
    txn = Transaction(
        user_id=user.id, statement_id=stmt_id, date=date(2025, 3, 1),
        description="HUGE PURCHASE", amount=Decimal("-9999"),
        is_income=False, category="Shopping",
    )
    db_session.add(txn)
    await db_session.flush()

    # No history -> z-score cannot be computed -> nothing flagged
    flagged = await detect_zscore_anomalies(db_session, user.id, stmt_id)
    assert flagged == 0


# ── Dashboard endpoint integration tests ─────────────────────

@pytest.mark.asyncio
async def test_dashboard_overview_empty(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    resp = await client.get("/api/v1/dashboard/overview", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["income"] == 0.0
    assert data["expenses"] == 0.0
    assert data["savings_rate"] == 0.0


@pytest.mark.asyncio
async def test_dashboard_overview_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/dashboard/overview")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_spending_by_category_empty(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    resp = await client.get("/api/v1/dashboard/spending-by-category", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["categories"] == []


@pytest.mark.asyncio
async def test_spending_trend_empty(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    resp = await client.get("/api/v1/dashboard/spending-trend", headers=headers)
    assert resp.status_code == 200
    assert isinstance(resp.json()["trend"], list)


@pytest.mark.asyncio
async def test_savings_rate_empty(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    resp = await client.get("/api/v1/dashboard/savings-rate", headers=headers)
    assert resp.status_code == 200
    assert isinstance(resp.json()["trend"], list)


@pytest.mark.asyncio
async def test_dashboard_with_data(client: AsyncClient, db_session: AsyncSession) -> None:
    """Seed transactions and verify dashboard returns correct aggregates."""
    resp = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    from app.utils.security import decode_access_token
    payload = decode_access_token(token)
    user_id = uuid.UUID(payload["sub"])

    await _seed_transactions(db_session, user_id)

    today = date.today()
    resp = await client.get(
        f"/api/v1/dashboard/overview?year={today.year}&month={today.month}",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["income"] == pytest.approx(3000.0)
    assert data["expenses"] == pytest.approx(1475.0)  # 1200+200+15+60
    assert data["savings_rate"] > 0


@pytest.mark.asyncio
async def test_spending_by_category_with_data(client: AsyncClient, db_session: AsyncSession) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "cat_test@test.com", "password": "SecurePass123"},
    )
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    from app.utils.security import decode_access_token
    user_id = uuid.UUID(decode_access_token(token)["sub"])

    await _seed_transactions(db_session, user_id)

    today = date.today()
    resp = await client.get(
        f"/api/v1/dashboard/spending-by-category?year={today.year}&month={today.month}",
        headers=headers,
    )
    assert resp.status_code == 200
    categories = resp.json()["categories"]
    assert len(categories) >= 4  # Housing, Groceries, Entertainment, Transportation
    cat_names = [c["category"] for c in categories]
    assert "Housing" in cat_names
    assert "Groceries" in cat_names

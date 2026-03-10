"""
Tests for budget endpoints and ML prediction service.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_auth import REGISTER_PAYLOAD
from app.models.transaction import Transaction
from app.models.budget import Budget
from app.services.ml_service import predict_spending_for_user, _next_month_start


# ── Helpers ───────────────────────────────────────────────────

async def _auth_headers(client: AsyncClient) -> dict:
    resp = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _register(client: AsyncClient, email: str) -> dict:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "SecurePass123"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _get_user_id(client: AsyncClient, headers: dict) -> uuid.UUID:
    from app.utils.security import decode_access_token
    token = headers["Authorization"].split(" ")[1]
    return uuid.UUID(decode_access_token(token)["sub"])


def _months_ago(n: int) -> tuple[int, int]:
    """Return (year, month) for n months before today."""
    today = date.today()
    y, m = today.year, today.month - n
    while m <= 0:
        y -= 1
        m += 12
    return y, m


def _make_transaction(
    user_id: uuid.UUID,
    category: str,
    amount: Decimal,
    year: int,
    month: int,
    day: int = 15,
) -> Transaction:
    stmt_id = uuid.uuid4()
    return Transaction(
        user_id=user_id,
        statement_id=stmt_id,
        date=date(year, month, day),
        description=f"{category.upper()} PAYMENT",
        amount=amount,
        is_income=False,
        category=category,
    )


# ── ML service unit tests ─────────────────────────────────────

@pytest.mark.asyncio
async def test_predict_no_history_returns_empty(db_session: AsyncSession) -> None:
    """No transactions → empty predictions."""
    from app.models.user import User
    from app.utils.security import hash_password
    user = User(email="ml_empty@test.com", password_hash=hash_password("pass"))
    db_session.add(user)
    await db_session.flush()

    predictions = await predict_spending_for_user(db_session, user.id)
    assert predictions == []


@pytest.mark.asyncio
async def test_predict_single_month_uses_moving_average(db_session: AsyncSession) -> None:
    """Only one month of data → moving-average fallback."""
    from app.models.user import User
    from app.utils.security import hash_password
    user = User(email="ml_single@test.com", password_hash=hash_password("pass"))
    db_session.add(user)
    await db_session.flush()

    # Use a date within the 6-month lookback window
    y, m = _months_ago(2)
    txn = _make_transaction(user.id, "Groceries", Decimal("-300"), y, m)
    db_session.add(txn)
    await db_session.flush()

    predictions = await predict_spending_for_user(db_session, user.id)
    assert len(predictions) == 1
    pred = predictions[0]
    assert pred["category"] == "Groceries"
    assert pred["prediction_method"] == "moving_average"
    assert pred["predicted_spend"] == pytest.approx(300.0, rel=0.01)


@pytest.mark.asyncio
async def test_predict_multi_month_uses_linear_regression(db_session: AsyncSession) -> None:
    """Two or more months → linear regression."""
    from app.models.user import User
    from app.utils.security import hash_password
    user = User(email="ml_multi@test.com", password_hash=hash_password("pass"))
    db_session.add(user)
    await db_session.flush()

    # Use 3 recent months within the 6-month lookback window
    amounts = ["-200", "-220", "-240"]
    for offset, amount in zip([5, 4, 3], amounts):
        y, m = _months_ago(offset)
        txn = _make_transaction(user.id, "Dining", Decimal(amount), y, m)
        db_session.add(txn)
    await db_session.flush()

    predictions = await predict_spending_for_user(db_session, user.id)
    assert len(predictions) == 1
    pred = predictions[0]
    assert pred["prediction_method"] == "linear_regression"
    # Trend is +20/month → next value should be > 0
    assert pred["predicted_spend"] > 0


@pytest.mark.asyncio
async def test_predict_upserts_budget_row(db_session: AsyncSession) -> None:
    """Predictions should be stored in the budgets table."""
    from sqlalchemy import select
    from app.models.user import User
    from app.utils.security import hash_password
    user = User(email="ml_upsert@test.com", password_hash=hash_password("pass"))
    db_session.add(user)
    await db_session.flush()

    # Use recent months within the 6-month lookback window
    for offset in [4, 3]:
        y, m = _months_ago(offset)
        txn = _make_transaction(user.id, "Housing", Decimal("-1200"), y, m)
        db_session.add(txn)
    await db_session.flush()

    target = _next_month_start()
    await predict_spending_for_user(db_session, user.id, target_month=target)

    result = await db_session.execute(
        select(Budget).where(
            Budget.user_id == user.id,
            Budget.category == "Housing",
            Budget.month == target,
        )
    )
    budget = result.scalar_one_or_none()
    assert budget is not None
    assert budget.predicted_spend is not None
    assert float(budget.predicted_spend) > 0


@pytest.mark.asyncio
async def test_predict_ignores_income(db_session: AsyncSession) -> None:
    """Income transactions should not be included in predictions."""
    from app.models.user import User
    from app.utils.security import hash_password
    user = User(email="ml_income@test.com", password_hash=hash_password("pass"))
    db_session.add(user)
    await db_session.flush()

    # Only income transactions
    for month in [1, 2]:
        txn = Transaction(
            user_id=user.id,
            statement_id=uuid.uuid4(),
            date=date(2025, month, 1),
            description="SALARY",
            amount=Decimal("3000"),
            is_income=True,
            category="Income",
        )
        db_session.add(txn)
    await db_session.flush()

    predictions = await predict_spending_for_user(db_session, user.id)
    assert predictions == []


# ── Budget endpoint integration tests ────────────────────────

@pytest.mark.asyncio
async def test_list_budgets_empty(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    resp = await client.get("/api/v1/budgets/", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_budgets_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/budgets/")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_set_budget_creates_row(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    today = date.today()
    payload = {
        "category": "Groceries",
        "month": f"{today.year}-{today.month:02d}-01",
        "monthly_limit": "500.00",
    }
    resp = await client.post("/api/v1/budgets/", json=payload, headers=headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["category"] == "Groceries"
    assert float(data["monthly_limit"]) == 500.0


@pytest.mark.asyncio
async def test_set_budget_updates_existing(client: AsyncClient) -> None:
    """POSTing the same (category, month) twice should update the limit."""
    headers = await _auth_headers(client)
    today = date.today()
    payload = {
        "category": "Entertainment",
        "month": f"{today.year}-{today.month:02d}-01",
        "monthly_limit": "100.00",
    }
    await client.post("/api/v1/budgets/", json=payload, headers=headers)

    payload["monthly_limit"] = "150.00"
    resp = await client.post("/api/v1/budgets/", json=payload, headers=headers)
    assert resp.status_code == 201
    assert float(resp.json()["monthly_limit"]) == 150.0


@pytest.mark.asyncio
async def test_get_predictions_empty(client: AsyncClient) -> None:
    """No transaction history → empty predictions list."""
    headers = await _auth_headers(client)
    resp = await client.get("/api/v1/budgets/predictions", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 0
    assert data["predictions"] == []


@pytest.mark.asyncio
async def test_get_predictions_with_data(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Historical transactions → predictions returned per category."""
    headers = await _register(client, "budget_pred@test.com")
    user_id = await _get_user_id(client, headers)

    # Use recent months within the 6-month lookback window
    amounts = ["-300", "-320", "-310"]
    for offset, amount in zip([5, 4, 3], amounts):
        y, m = _months_ago(offset)
        txn = _make_transaction(user_id, "Groceries", Decimal(amount), y, m)
        db_session.add(txn)
    await db_session.commit()

    resp = await client.get("/api/v1/budgets/predictions", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1
    categories = [p["category"] for p in data["predictions"]]
    assert "Groceries" in categories


@pytest.mark.asyncio
async def test_get_vs_actual_empty(client: AsyncClient) -> None:
    """No data → empty items list."""
    headers = await _auth_headers(client)
    resp = await client.get("/api/v1/budgets/vs-actual", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []


@pytest.mark.asyncio
async def test_get_vs_actual_with_budget_and_spending(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Budget set + actual spending → vs-actual returns variance."""
    headers = await _register(client, "budget_vs@test.com")
    user_id = await _get_user_id(client, headers)

    today = date.today()
    # Seed a transaction this month
    txn = Transaction(
        user_id=user_id,
        statement_id=uuid.uuid4(),
        date=today,
        description="GROCERIES",
        amount=Decimal("-350"),
        is_income=False,
        category="Groceries",
    )
    db_session.add(txn)
    await db_session.commit()

    # Set a budget limit
    payload = {
        "category": "Groceries",
        "month": f"{today.year}-{today.month:02d}-01",
        "monthly_limit": "300.00",
    }
    await client.post("/api/v1/budgets/", json=payload, headers=headers)

    resp = await client.get(
        f"/api/v1/budgets/vs-actual?year={today.year}&month={today.month}",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    items = data["items"]
    assert len(items) >= 1
    groceries_item = next((i for i in items if i["category"] == "Groceries"), None)
    assert groceries_item is not None
    assert groceries_item["actual_spend"] == pytest.approx(350.0)
    assert groceries_item["monthly_limit"] == pytest.approx(300.0)
    assert groceries_item["variance"] == pytest.approx(50.0)  # 350 - 300

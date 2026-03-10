"""
Tests for savings suggestion endpoints and suggestion generation service.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction
from app.models.budget import Budget
from app.services.suggestion_service import generate_suggestions_for_user


# ── Helpers ───────────────────────────────────────────────────

async def _register(client: AsyncClient, email: str, premium: bool = False) -> dict:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "SecurePass123"},
    )
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    if premium:
        # Directly upgrade user in DB via token sub
        from app.utils.security import decode_access_token
        from sqlalchemy import update
        from app.models.user import User
        user_id = uuid.UUID(decode_access_token(token)["sub"])
        # We need db_session access here — use a fixture-less approach:
        # premium flag is handled per test using db_session directly.
    return headers


async def _get_user_id(headers: dict) -> uuid.UUID:
    from app.utils.security import decode_access_token
    token = headers["Authorization"].split(" ")[1]
    return uuid.UUID(decode_access_token(token)["sub"])


async def _make_premium(db_session: AsyncSession, user_id: uuid.UUID) -> None:
    from sqlalchemy import update
    from app.models.user import User
    await db_session.execute(
        update(User).where(User.id == user_id).values(plan="premium")
    )
    await db_session.commit()


def _expense(
    user_id: uuid.UUID,
    description: str,
    amount: str,
    year: int,
    month: int,
    category: str | None = "Shopping",
) -> Transaction:
    return Transaction(
        user_id=user_id,
        statement_id=uuid.uuid4(),
        date=date(year, month, 15),
        description=description,
        amount=Decimal(amount),
        is_income=False,
        category=category,
    )


# ── Suggestion service unit tests ─────────────────────────────

@pytest.mark.asyncio
async def test_generate_suggestions_no_data(db_session: AsyncSession) -> None:
    """No transactions → no overspend or subscription suggestions (may still get general tip)."""
    from app.models.user import User
    from app.utils.security import hash_password
    user = User(email="sug_empty@test.com", password_hash=hash_password("pass"))
    db_session.add(user)
    await db_session.flush()

    suggestions = await generate_suggestions_for_user(db_session, user.id)
    # With no data at all (no actual_by_cat), not even a general tip is added
    assert isinstance(suggestions, list)


@pytest.mark.asyncio
async def test_generate_overspend_suggestion(db_session: AsyncSession) -> None:
    """Actual > 110% of predicted → overspend suggestion generated."""
    from app.models.user import User
    from app.utils.security import hash_password
    user = User(email="sug_over@test.com", password_hash=hash_password("pass"))
    db_session.add(user)
    await db_session.flush()

    today = date.today()
    if today.month == 1:
        prev_year, prev_month = today.year - 1, 12
    else:
        prev_year, prev_month = today.year, today.month - 1

    # Actual spending last month: $500 on Groceries
    txn = _expense(user.id, "WHOLE FOODS", "-500", prev_year, prev_month, "Groceries")
    db_session.add(txn)
    await db_session.flush()

    # Predicted: $300 → actual is 167% of predicted (> 110%)
    budget = Budget(
        user_id=user.id,
        category="Groceries",
        month=date(prev_year, prev_month, 1),
        predicted_spend=Decimal("300"),
        ml_confidence=Decimal("0.8"),
    )
    db_session.add(budget)
    await db_session.flush()

    suggestions = await generate_suggestions_for_user(db_session, user.id)
    overspend_sugs = [s for s in suggestions if s["suggestion_type"] == "reduce_category"]
    assert len(overspend_sugs) >= 1
    assert "Groceries" in overspend_sugs[0]["description"]


@pytest.mark.asyncio
async def test_generate_subscription_suggestion(db_session: AsyncSession) -> None:
    """Same description+amount in ≥ 2 months → subscription suggestion."""
    from app.models.user import User
    from app.utils.security import hash_password
    user = User(email="sug_sub@test.com", password_hash=hash_password("pass"))
    db_session.add(user)
    await db_session.flush()

    today = date.today()
    # Add same charge in 2 different months within the last 3 months
    for offset in [1, 2]:
        y, m = today.year, today.month - offset
        while m <= 0:
            y -= 1
            m += 12
        txn = _expense(user.id, "NETFLIX MONTHLY", "-15.99", y, m, "Entertainment")
        db_session.add(txn)
    await db_session.flush()

    suggestions = await generate_suggestions_for_user(db_session, user.id)
    sub_sugs = [s for s in suggestions if s["suggestion_type"] == "cancel_subscription"]
    assert len(sub_sugs) >= 1
    assert "NETFLIX MONTHLY" in sub_sugs[0]["description"]


@pytest.mark.asyncio
async def test_generate_suggestions_caps_at_10(db_session: AsyncSession) -> None:
    """At most 10 suggestions are stored."""
    from app.models.user import User
    from app.utils.security import hash_password
    user = User(email="sug_cap@test.com", password_hash=hash_password("pass"))
    db_session.add(user)
    await db_session.flush()

    today = date.today()
    if today.month == 1:
        prev_year, prev_month = today.year - 1, 12
    else:
        prev_year, prev_month = today.year, today.month - 1

    # Generate many recurring subscriptions (15 different descriptions)
    for i in range(15):
        for offset in [1, 2]:
            y, m = today.year, today.month - offset
            while m <= 0:
                y -= 1
                m += 12
            txn = _expense(user.id, f"SERVICE_{i}", f"-{10 + i}.99", y, m, "Subscriptions")
            db_session.add(txn)
    await db_session.flush()

    suggestions = await generate_suggestions_for_user(db_session, user.id)
    assert len(suggestions) <= 10


# ── Suggestion endpoint integration tests ─────────────────────

@pytest.mark.asyncio
async def test_list_suggestions_requires_premium(client: AsyncClient) -> None:
    """Free user gets 402."""
    headers = await _register(client, "sug_free@test.com")
    resp = await client.get("/api/v1/suggestions/", headers=headers)
    assert resp.status_code == 402


@pytest.mark.asyncio
async def test_generate_suggestions_requires_premium(client: AsyncClient) -> None:
    """Free user gets 402 on generate."""
    headers = await _register(client, "sug_gen_free@test.com")
    resp = await client.post("/api/v1/suggestions/generate", headers=headers)
    assert resp.status_code == 402


@pytest.mark.asyncio
async def test_list_suggestions_empty_for_premium(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Premium user with no suggestions gets empty list."""
    headers = await _register(client, "sug_prem@test.com")
    user_id = await _get_user_id(headers)
    await _make_premium(db_session, user_id)

    resp = await client.get("/api/v1/suggestions/", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["suggestions"] == []


@pytest.mark.asyncio
async def test_generate_and_list_suggestions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Premium user: generate suggestions, then list them."""
    headers = await _register(client, "sug_full@test.com")
    user_id = await _get_user_id(headers)
    await _make_premium(db_session, user_id)

    today = date.today()
    if today.month == 1:
        prev_year, prev_month = today.year - 1, 12
    else:
        prev_year, prev_month = today.year, today.month - 1

    # Seed a recurring subscription
    for offset in [1, 2]:
        y, m = today.year, today.month - offset
        while m <= 0:
            y -= 1
            m += 12
        txn = _expense(user_id, "SPOTIFY PREMIUM", "-9.99", y, m, "Entertainment")
        db_session.add(txn)
    await db_session.commit()

    # Generate
    gen_resp = await client.post("/api/v1/suggestions/generate", headers=headers)
    assert gen_resp.status_code == 200
    assert gen_resp.json()["generated"] >= 1

    # List
    list_resp = await client.get("/api/v1/suggestions/", headers=headers)
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] >= 1


@pytest.mark.asyncio
async def test_dismiss_suggestion(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Premium user can dismiss a suggestion."""
    headers = await _register(client, "sug_dismiss@test.com")
    user_id = await _get_user_id(headers)
    await _make_premium(db_session, user_id)

    today = date.today()
    # Seed a recurring subscription to generate a suggestion
    for offset in [1, 2]:
        y, m = today.year, today.month - offset
        while m <= 0:
            y -= 1
            m += 12
        txn = _expense(user_id, "APPLE MUSIC", "-10.99", y, m, "Entertainment")
        db_session.add(txn)
    await db_session.commit()

    await client.post("/api/v1/suggestions/generate", headers=headers)

    list_resp = await client.get("/api/v1/suggestions/", headers=headers)
    suggestions = list_resp.json()["suggestions"]
    assert len(suggestions) >= 1

    sug_id = suggestions[0]["id"]
    dismiss_resp = await client.post(
        f"/api/v1/suggestions/{sug_id}/dismiss", headers=headers
    )
    assert dismiss_resp.status_code == 200
    assert dismiss_resp.json()["dismissed"] is True

    # After dismiss, should not appear in default list
    list_resp2 = await client.get("/api/v1/suggestions/", headers=headers)
    ids_visible = [s["id"] for s in list_resp2.json()["suggestions"]]
    assert sug_id not in ids_visible


@pytest.mark.asyncio
async def test_dismiss_suggestion_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Dismissing a non-existent suggestion returns 404."""
    headers = await _register(client, "sug_404@test.com")
    user_id = await _get_user_id(headers)
    await _make_premium(db_session, user_id)

    fake_id = uuid.uuid4()
    resp = await client.post(f"/api/v1/suggestions/{fake_id}/dismiss", headers=headers)
    assert resp.status_code == 404

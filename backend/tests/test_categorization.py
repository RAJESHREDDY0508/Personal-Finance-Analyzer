"""
Unit tests for AI categorization service and transaction endpoints.
"""
import uuid
from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient
from tests.test_auth import REGISTER_PAYLOAD
from app.services.ai_service import (
    CATEGORIES,
    _rule_based_category,
    _rule_based_batch,
    categorize_batch,
)


async def _auth_headers(client: AsyncClient) -> dict:
    resp = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_rule_starbucks():
    assert _rule_based_category("STARBUCKS #1234") == "Food & Dining"

def test_rule_whole_foods():
    assert _rule_based_category("WHOLE FOODS MARKET #123") == "Groceries"

def test_rule_uber():
    assert _rule_based_category("UBER *TRIP") == "Transportation"

def test_rule_netflix():
    assert _rule_based_category("NETFLIX.COM") == "Entertainment"

def test_rule_cvs():
    assert _rule_based_category("CVS PHARMACY") == "Health & Medical"

def test_rule_amazon():
    assert _rule_based_category("AMAZON.COM AMZN") == "Shopping"

def test_rule_payroll():
    assert _rule_based_category("DIRECT DEPOSIT PAYROLL XYZ") == "Income"

def test_rule_unknown_returns_none():
    assert _rule_based_category("ZXQWERTY123456 UNKNOWN") is None

def test_rule_batch_five():
    descs = ["STARBUCKS", "WHOLE FOODS", "UBER TRIP", "NETFLIX", "CVS PHARMACY"]
    res = _rule_based_batch(descs)
    cats = [r["category"] for r in res]
    assert cats == ["Food & Dining", "Groceries", "Transportation", "Entertainment", "Health & Medical"]

def test_rule_batch_unknown_defaults_other():
    res = _rule_based_batch(["XYZZY UNKNOWN"])
    assert res[0]["category"] == "Other"

def test_all_categories_defined():
    assert len(CATEGORIES) >= 15
    assert "Food & Dining" in CATEGORIES
    assert "Income" in CATEGORIES
    assert "Other" in CATEGORIES


@pytest.mark.asyncio
async def test_categorize_batch_fallback_on_error():
    with patch("app.services.ai_service.settings") as ms,          patch("app.services.ai_service.AsyncOpenAI") as mock_cls:
        ms.openai_api_key = "sk-real-key"
        mc = AsyncMock()
        mock_cls.return_value = mc
        mc.chat.completions.create = AsyncMock(side_effect=Exception("timeout"))
        result = await categorize_batch(["STARBUCKS", "UNKNOWN XYZ"])
    assert result[0]["category"] == "Food & Dining"
    assert result[1]["category"] == "Other"


@pytest.mark.asyncio
async def test_categorize_batch_no_api_key():
    with patch("app.services.ai_service.settings") as ms:
        ms.openai_api_key = "sk-placeholder"
        result = await categorize_batch(["NETFLIX MONTHLY"])
    assert result[0]["category"] == "Entertainment"


@pytest.mark.asyncio
async def test_list_transactions_empty(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    resp = await client.get("/api/v1/transactions", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["transactions"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_transactions_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/transactions")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_transaction_not_found(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    resp = await client.get(f"/api/v1/transactions/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_category_not_found(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    resp = await client.patch(
        f"/api/v1/transactions/{uuid.uuid4()}/category",
        json={"category": "Groceries"},
        headers=headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_transaction_isolation_between_users(client: AsyncClient) -> None:
    resp_a = await client.post("/api/v1/auth/register",
        json={"email": "user_a@test.com", "password": "SecurePass123"})
    ha = {"Authorization": f"Bearer {resp_a.json()['access_token']}"}

    resp_b = await client.post("/api/v1/auth/register",
        json={"email": "user_b@test.com", "password": "SecurePass123"})
    hb = {"Authorization": f"Bearer {resp_b.json()['access_token']}"}

    assert (await client.get("/api/v1/transactions", headers=ha)).json()["total"] == 0
    assert (await client.get("/api/v1/transactions", headers=hb)).json()["total"] == 0

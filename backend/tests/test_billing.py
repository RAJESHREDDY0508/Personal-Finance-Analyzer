"""
Tests for Stripe billing service and billing API endpoints.

All Stripe SDK calls are mocked — no real Stripe credentials required.
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.billing_service import (
    PLANS,
    _on_checkout_completed,
    _on_subscription_deleted,
    _on_subscription_updated,
    create_checkout_session,
    create_portal_session,
    get_subscription_status,
)

# ── Helpers ───────────────────────────────────────────────────

REGISTER_PAYLOAD = {"email": "billing_user@example.com", "password": "BillingPass123"}


async def _auth_headers(client: AsyncClient) -> dict:
    resp = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert resp.status_code in (200, 201)
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _get_user(db: AsyncSession, headers: dict) -> User:
    from app.utils.security import decode_access_token
    token = headers["Authorization"].split(" ")[1]
    user_id = uuid.UUID(decode_access_token(token)["sub"])
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one()


def _make_stripe_event(event_type: str, data_object: dict) -> MagicMock:
    """Build a minimal stripe.Event-like MagicMock."""
    event = MagicMock()
    event.__getitem__ = lambda self, key: {
        "type": event_type,
        "id": "evt_test_123",
        "data": {"object": data_object},
    }[key]
    return event


# ── PLANS catalogue tests ─────────────────────────────────────

def test_plans_catalogue_has_two_entries():
    assert len(PLANS) == 2


def test_plans_free_is_zero_price():
    free = next(p for p in PLANS if p["name"] == "Free")
    assert free["price"] == 0.0


def test_plans_premium_price():
    premium = next(p for p in PLANS if p["name"] == "Premium")
    assert premium["price"] == 9.99
    assert "AI savings suggestions" in premium["features"]


# ── billing_service unit tests ────────────────────────────────

@pytest.mark.anyio
async def test_create_checkout_session_returns_url(db_session: AsyncSession, client: AsyncClient):
    """create_checkout_session should call stripe and return the hosted URL."""
    headers = await _auth_headers(client)
    user = await _get_user(db_session, headers)

    mock_session = MagicMock()
    mock_session.url = "https://checkout.stripe.com/pay/cs_test_abc"

    with patch("app.services.billing_service.stripe.checkout.Session.create", return_value=mock_session):
        url = await create_checkout_session(
            user,
            success_url="http://localhost:3000/dashboard?checkout=success",
            cancel_url="http://localhost:3000/settings?checkout=cancelled",
        )

    assert url == "https://checkout.stripe.com/pay/cs_test_abc"


@pytest.mark.anyio
async def test_create_checkout_session_uses_existing_customer(
    db_session: AsyncSession, client: AsyncClient
):
    """If the user already has a stripe_customer_id, it should be passed as customer=."""
    headers = await _auth_headers(client)
    user = await _get_user(db_session, headers)
    user.stripe_customer_id = "cus_existing_123"
    await db_session.commit()

    mock_session = MagicMock()
    mock_session.url = "https://checkout.stripe.com/pay/cs_existing"

    with patch(
        "app.services.billing_service.stripe.checkout.Session.create",
        return_value=mock_session,
    ) as mock_create:
        await create_checkout_session(user, "http://ok", "http://cancel")

    call_kwargs = mock_create.call_args[1]
    assert call_kwargs.get("customer") == "cus_existing_123"
    assert "customer_email" not in call_kwargs


@pytest.mark.anyio
async def test_create_portal_session_returns_url(db_session: AsyncSession, client: AsyncClient):
    """create_portal_session should call Stripe and return the portal URL."""
    headers = await _auth_headers(client)
    user = await _get_user(db_session, headers)
    user.stripe_customer_id = "cus_portal_123"
    await db_session.commit()

    mock_session = MagicMock()
    mock_session.url = "https://billing.stripe.com/p/session_abc"

    with patch(
        "app.services.billing_service.stripe.billing_portal.Session.create",
        return_value=mock_session,
    ):
        url = await create_portal_session(user, "http://localhost:3000/settings")

    assert url == "https://billing.stripe.com/p/session_abc"


@pytest.mark.anyio
async def test_create_portal_session_no_customer_raises(
    db_session: AsyncSession, client: AsyncClient
):
    """create_portal_session raises ValueError if user has no stripe_customer_id."""
    headers = await _auth_headers(client)
    user = await _get_user(db_session, headers)
    user.stripe_customer_id = None
    await db_session.commit()

    with pytest.raises(ValueError, match="No Stripe customer"):
        await create_portal_session(user, "http://localhost:3000/settings")


@pytest.mark.anyio
async def test_get_subscription_status_no_subscription(
    db_session: AsyncSession, client: AsyncClient
):
    """User without a subscription gets status='none'."""
    headers = await _auth_headers(client)
    user = await _get_user(db_session, headers)
    # No stripe_subscription_id set

    status_data = await get_subscription_status(user)

    assert status_data["plan"] == "free"
    assert status_data["status"] == "none"
    assert status_data["current_period_end"] is None


@pytest.mark.anyio
async def test_get_subscription_status_from_stripe(
    db_session: AsyncSession, client: AsyncClient
):
    """get_subscription_status should call Stripe and return active subscription data."""
    headers = await _auth_headers(client)
    user = await _get_user(db_session, headers)
    user.stripe_subscription_id = "sub_test_abc"
    user.plan = "premium"
    await db_session.commit()

    mock_sub = MagicMock()
    mock_sub.status = "active"
    mock_sub.current_period_end = 1893456000  # some future timestamp

    with patch("app.services.billing_service.stripe.Subscription.retrieve", return_value=mock_sub):
        status_data = await get_subscription_status(user)

    assert status_data["plan"] == "premium"
    assert status_data["status"] == "active"
    assert status_data["current_period_end"] is not None


# ── Webhook handler unit tests ────────────────────────────────

@pytest.mark.anyio
async def test_on_checkout_completed_upgrades_user(
    db_session: AsyncSession, client: AsyncClient
):
    """checkout.session.completed should upgrade user to premium."""
    headers = await _auth_headers(client)
    user = await _get_user(db_session, headers)
    assert user.plan == "free"

    session_data = {
        "metadata": {"user_id": str(user.id)},
        "client_reference_id": str(user.id),
        "customer": "cus_webhook_123",
        "subscription": "sub_webhook_abc",
    }

    await _on_checkout_completed(db_session, session_data)
    await db_session.refresh(user)

    assert user.plan == "premium"
    assert user.stripe_customer_id == "cus_webhook_123"
    assert user.stripe_subscription_id == "sub_webhook_abc"


@pytest.mark.anyio
async def test_on_checkout_completed_missing_user_id(db_session: AsyncSession):
    """checkout.session.completed with no user_id should log and return without error."""
    # No user_id in metadata and no client_reference_id — should not raise
    await _on_checkout_completed(db_session, {"metadata": {}, "customer": "cus_x"})


@pytest.mark.anyio
async def test_on_subscription_deleted_downgrades_user(
    db_session: AsyncSession, client: AsyncClient
):
    """customer.subscription.deleted should downgrade user to free."""
    headers = await _auth_headers(client)
    user = await _get_user(db_session, headers)
    user.plan = "premium"
    user.stripe_customer_id = "cus_delete_test"
    user.stripe_subscription_id = "sub_delete_abc"
    await db_session.commit()

    await _on_subscription_deleted(db_session, {"customer": "cus_delete_test"})
    await db_session.refresh(user)

    assert user.plan == "free"
    assert user.stripe_subscription_id is None


@pytest.mark.anyio
async def test_on_subscription_updated_active(
    db_session: AsyncSession, client: AsyncClient
):
    """customer.subscription.updated with status=active should set plan to premium."""
    headers = await _auth_headers(client)
    user = await _get_user(db_session, headers)
    user.stripe_customer_id = "cus_update_active"
    await db_session.commit()

    await _on_subscription_updated(
        db_session,
        {"customer": "cus_update_active", "status": "active", "id": "sub_new_abc"},
    )
    await db_session.refresh(user)
    assert user.plan == "premium"
    assert user.stripe_subscription_id == "sub_new_abc"


@pytest.mark.anyio
async def test_on_subscription_updated_canceled(
    db_session: AsyncSession, client: AsyncClient
):
    """customer.subscription.updated with status=canceled should downgrade to free."""
    headers = await _auth_headers(client)
    user = await _get_user(db_session, headers)
    user.plan = "premium"
    user.stripe_customer_id = "cus_update_cancel"
    user.stripe_subscription_id = "sub_old"
    await db_session.commit()

    await _on_subscription_updated(
        db_session,
        {"customer": "cus_update_cancel", "status": "canceled", "id": "sub_old"},
    )
    await db_session.refresh(user)
    assert user.plan == "free"
    assert user.stripe_subscription_id is None


# ── API endpoint tests ────────────────────────────────────────

@pytest.mark.anyio
async def test_list_plans_no_auth(client: AsyncClient):
    """GET /billing/plans is public and returns two plans."""
    resp = await client.get("/api/v1/billing/plans")
    assert resp.status_code == 200
    plans = resp.json()
    assert len(plans) == 2
    names = [p["name"] for p in plans]
    assert "Free" in names
    assert "Premium" in names


@pytest.mark.anyio
async def test_checkout_endpoint_returns_url(client: AsyncClient):
    """POST /billing/checkout returns a checkout_url."""
    headers = await _auth_headers(client)

    mock_session = MagicMock()
    mock_session.url = "https://checkout.stripe.com/pay/cs_api_test"

    with patch(
        "app.services.billing_service.stripe.checkout.Session.create",
        return_value=mock_session,
    ):
        resp = await client.post("/api/v1/billing/checkout", headers=headers)

    assert resp.status_code == 200
    assert resp.json()["checkout_url"] == "https://checkout.stripe.com/pay/cs_api_test"


@pytest.mark.anyio
async def test_checkout_endpoint_requires_auth(client: AsyncClient):
    resp = await client.post("/api/v1/billing/checkout")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_portal_endpoint_no_customer_returns_400(client: AsyncClient):
    """POST /billing/portal returns 400 if user has no Stripe customer."""
    headers = await _auth_headers(client)
    resp = await client.post("/api/v1/billing/portal", headers=headers)
    assert resp.status_code == 400
    assert "No Stripe customer" in resp.json()["detail"]


@pytest.mark.anyio
async def test_portal_endpoint_returns_url(
    client: AsyncClient, db_session: AsyncSession
):
    """POST /billing/portal returns portal_url for a user with a Stripe customer."""
    headers = await _auth_headers(client)
    user = await _get_user(db_session, headers)
    user.stripe_customer_id = "cus_portal_api"
    await db_session.commit()

    mock_session = MagicMock()
    mock_session.url = "https://billing.stripe.com/p/portal_api"

    with patch(
        "app.services.billing_service.stripe.billing_portal.Session.create",
        return_value=mock_session,
    ):
        resp = await client.post("/api/v1/billing/portal", headers=headers)

    assert resp.status_code == 200
    assert resp.json()["portal_url"] == "https://billing.stripe.com/p/portal_api"


@pytest.mark.anyio
async def test_subscription_endpoint_free_user(client: AsyncClient):
    """GET /billing/subscription returns plan=free, status=none for a new user."""
    headers = await _auth_headers(client)
    resp = await client.get("/api/v1/billing/subscription", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["plan"] == "free"
    assert data["status"] == "none"
    assert data["current_period_end"] is None


@pytest.mark.anyio
async def test_subscription_endpoint_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/billing/subscription")
    assert resp.status_code == 401


# ── Webhook endpoint tests ────────────────────────────────────

@pytest.mark.anyio
async def test_webhook_invalid_signature_returns_400(client: AsyncClient):
    """POST /billing/webhook with bad signature returns 400."""
    import stripe as stripe_lib

    with patch(
        "app.services.billing_service.stripe.Webhook.construct_event",
        side_effect=stripe_lib.SignatureVerificationError("bad sig", "sig_header"),
    ):
        resp = await client.post(
            "/api/v1/billing/webhook",
            content=b'{"type":"test"}',
            headers={"stripe-signature": "bad_sig", "content-type": "application/json"},
        )

    assert resp.status_code == 400
    assert "signature" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_webhook_checkout_completed_upgrades_user(
    client: AsyncClient, db_session: AsyncSession
):
    """A valid checkout.session.completed webhook upgrades the user to premium."""
    headers = await _auth_headers(client)
    user = await _get_user(db_session, headers)

    checkout_session_data = {
        "metadata": {"user_id": str(user.id)},
        "client_reference_id": str(user.id),
        "customer": "cus_wh_upgrade",
        "subscription": "sub_wh_upgrade",
    }
    event_payload = {
        "type": "checkout.session.completed",
        "id": "evt_wh_upgrade",
        "data": {"object": checkout_session_data},
    }
    raw_body = json.dumps(event_payload).encode()

    mock_event = MagicMock()
    mock_event.__getitem__ = lambda self, k: event_payload[k]

    with patch(
        "app.services.billing_service.stripe.Webhook.construct_event",
        return_value=mock_event,
    ):
        resp = await client.post(
            "/api/v1/billing/webhook",
            content=raw_body,
            headers={"stripe-signature": "t=123,v1=abc", "content-type": "application/json"},
        )

    assert resp.status_code == 200
    assert resp.json() == {"received": True}

    await db_session.refresh(user)
    assert user.plan == "premium"
    assert user.stripe_customer_id == "cus_wh_upgrade"


@pytest.mark.anyio
async def test_webhook_subscription_deleted_downgrades_user(
    client: AsyncClient, db_session: AsyncSession
):
    """A valid customer.subscription.deleted webhook downgrades the user to free."""
    headers = await _auth_headers(client)
    user = await _get_user(db_session, headers)
    user.plan = "premium"
    user.stripe_customer_id = "cus_wh_delete"
    user.stripe_subscription_id = "sub_wh_delete"
    await db_session.commit()

    sub_data = {"customer": "cus_wh_delete", "id": "sub_wh_delete"}
    event_payload = {
        "type": "customer.subscription.deleted",
        "id": "evt_wh_delete",
        "data": {"object": sub_data},
    }
    raw_body = json.dumps(event_payload).encode()

    mock_event = MagicMock()
    mock_event.__getitem__ = lambda self, k: event_payload[k]

    with patch(
        "app.services.billing_service.stripe.Webhook.construct_event",
        return_value=mock_event,
    ):
        resp = await client.post(
            "/api/v1/billing/webhook",
            content=raw_body,
            headers={"stripe-signature": "t=456,v1=def", "content-type": "application/json"},
        )

    assert resp.status_code == 200

    await db_session.refresh(user)
    assert user.plan == "free"
    assert user.stripe_subscription_id is None


@pytest.mark.anyio
async def test_webhook_unknown_event_type_is_ignored(client: AsyncClient):
    """Unknown event types should return 200 without error."""
    event_payload = {
        "type": "payment_intent.created",
        "id": "evt_unknown",
        "data": {"object": {}},
    }
    raw_body = json.dumps(event_payload).encode()

    mock_event = MagicMock()
    mock_event.__getitem__ = lambda self, k: event_payload[k]

    with patch(
        "app.services.billing_service.stripe.Webhook.construct_event",
        return_value=mock_event,
    ):
        resp = await client.post(
            "/api/v1/billing/webhook",
            content=raw_body,
            headers={"stripe-signature": "t=789,v1=ghi", "content-type": "application/json"},
        )

    assert resp.status_code == 200


# ── Feature gating tests ──────────────────────────────────────

@pytest.mark.anyio
async def test_suggestions_blocked_for_free_user(client: AsyncClient):
    """GET /suggestions/ returns 402 for a free-tier user."""
    headers = await _auth_headers(client)
    resp = await client.get("/api/v1/suggestions/", headers=headers)
    assert resp.status_code == 402


@pytest.mark.anyio
async def test_suggestions_accessible_for_premium_user(
    client: AsyncClient, db_session: AsyncSession
):
    """GET /suggestions/ returns 200 after user is upgraded to premium."""
    headers = await _auth_headers(client)
    user = await _get_user(db_session, headers)
    user.plan = "premium"
    await db_session.commit()

    resp = await client.get("/api/v1/suggestions/", headers=headers)
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_generate_suggestions_blocked_for_free_user(client: AsyncClient):
    """POST /suggestions/generate returns 402 for a free-tier user."""
    headers = await _auth_headers(client)
    resp = await client.post("/api/v1/suggestions/generate", headers=headers)
    assert resp.status_code == 402

"""
Billing service — Stripe checkout, portal, subscription and webhook handling.

All Stripe SDK calls are synchronous (run in an executor) to avoid blocking
the async event loop.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import stripe
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User

logger = structlog.get_logger(__name__)


# ── Stripe initialisation ─────────────────────────────────────

def _configure_stripe() -> None:
    """Set global Stripe API key (idempotent)."""
    stripe.api_key = settings.stripe_secret_key


# ── Plan catalogue ────────────────────────────────────────────

PLANS = [
    {
        "name": "Free",
        "price": 0.0,
        "currency": "usd",
        "interval": "month",
        "features": [
            "Upload up to 3 bank statements/month",
            "Automatic transaction categorisation",
            "Dashboard analytics",
            "Anomaly detection",
        ],
    },
    {
        "name": "Premium",
        "price": 9.99,
        "currency": "usd",
        "interval": "month",
        "features": [
            "Unlimited statement uploads",
            "AI savings suggestions",
            "ML budget predictions",
            "Monthly email reports",
            "Priority support",
        ],
    },
]


# ── Checkout session ──────────────────────────────────────────

async def create_checkout_session(
    user: User,
    success_url: str,
    cancel_url: str,
) -> str:
    """
    Create a Stripe Checkout session for the Premium subscription.
    Returns the hosted checkout URL to redirect the user to.
    """
    _configure_stripe()

    def _call() -> str:
        kwargs: dict[str, Any] = dict(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{"price": settings.stripe_premium_price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=str(user.id),
            metadata={"user_id": str(user.id)},
        )
        # Attach existing Stripe customer if we have one
        if user.stripe_customer_id:
            kwargs["customer"] = user.stripe_customer_id
        else:
            kwargs["customer_email"] = user.email

        session = stripe.checkout.Session.create(**kwargs)
        return session.url or ""

    loop = asyncio.get_event_loop()
    url: str = await loop.run_in_executor(None, _call)
    logger.info("Stripe checkout session created", user_id=str(user.id))
    return url


# ── Billing portal ────────────────────────────────────────────

async def create_portal_session(
    user: User,
    return_url: str,
) -> str:
    """
    Create a Stripe Billing Portal session so the user can manage their
    subscription (cancel, update payment method, view invoices).
    Returns the portal URL.
    Raises ValueError if the user has no Stripe customer ID.
    """
    _configure_stripe()

    if not user.stripe_customer_id:
        raise ValueError("No Stripe customer associated with this account")

    def _call() -> str:
        session = stripe.billing_portal.Session.create(
            customer=user.stripe_customer_id,
            return_url=return_url,
        )
        return session.url

    loop = asyncio.get_event_loop()
    url: str = await loop.run_in_executor(None, _call)
    logger.info("Stripe portal session created", user_id=str(user.id))
    return url


# ── Subscription status ───────────────────────────────────────

async def get_subscription_status(user: User) -> dict:
    """
    Fetch the current subscription status for a user from Stripe.
    Returns a dict compatible with SubscriptionStatusResponse.
    """
    _configure_stripe()

    if not user.stripe_subscription_id:
        return {
            "plan": user.plan,
            "status": "none",
            "current_period_end": None,
        }

    def _call() -> stripe.Subscription:
        return stripe.Subscription.retrieve(user.stripe_subscription_id)  # type: ignore[arg-type]

    loop = asyncio.get_event_loop()
    subscription: stripe.Subscription = await loop.run_in_executor(None, _call)

    period_end: str | None = None
    if hasattr(subscription, "current_period_end") and subscription.current_period_end:
        period_end = datetime.fromtimestamp(
            subscription.current_period_end, tz=timezone.utc
        ).isoformat()

    return {
        "plan": user.plan,
        "status": subscription.status,
        "current_period_end": period_end,
    }


# ── Webhook signature verification ────────────────────────────

def verify_webhook(raw_body: bytes, stripe_signature: str) -> stripe.Event:
    """
    Verify Stripe webhook signature and return the parsed Event object.
    Raises stripe.SignatureVerificationError on invalid signature.
    Raises ValueError on malformed payload.
    """
    _configure_stripe()
    return stripe.Webhook.construct_event(
        payload=raw_body,
        sig_header=stripe_signature,
        secret=settings.stripe_webhook_secret,
    )


# ── Webhook event handlers ────────────────────────────────────

async def handle_webhook_event(db: AsyncSession, event: stripe.Event) -> None:
    """
    Dispatch a verified Stripe event to the correct handler.
    Unknown event types are silently ignored.
    """
    event_type: str = event["type"]
    data: dict = event["data"]["object"]

    logger.info("Stripe webhook received", event_type=event_type, event_id=event["id"])

    if event_type == "checkout.session.completed":
        await _on_checkout_completed(db, data)
    elif event_type == "customer.subscription.deleted":
        await _on_subscription_deleted(db, data)
    elif event_type == "customer.subscription.updated":
        await _on_subscription_updated(db, data)
    elif event_type == "invoice.payment_failed":
        await _on_payment_failed(db, data)
    else:
        logger.debug("Unhandled Stripe event type", event_type=event_type)


async def _on_checkout_completed(db: AsyncSession, session: dict) -> None:
    """
    checkout.session.completed — upgrade user to Premium.
    Sets stripe_customer_id and stripe_subscription_id on the user row.
    """
    user_id_str: str | None = (session.get("metadata") or {}).get("user_id")
    if not user_id_str:
        user_id_str = session.get("client_reference_id")
    if not user_id_str:
        logger.warning("checkout.session.completed missing user_id metadata")
        return

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        logger.error("Invalid user_id in checkout session metadata", value=user_id_str)
        return

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        logger.error("User not found for checkout completion", user_id=user_id_str)
        return

    user.plan = "premium"
    user.stripe_customer_id = session.get("customer")
    user.stripe_subscription_id = session.get("subscription")
    await db.commit()

    logger.info(
        "User upgraded to Premium",
        user_id=user_id_str,
        customer_id=user.stripe_customer_id,
    )


async def _on_subscription_deleted(db: AsyncSession, subscription: dict) -> None:
    """
    customer.subscription.deleted — downgrade user to Free.
    """
    customer_id: str | None = subscription.get("customer")
    if not customer_id:
        return

    result = await db.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        logger.warning("No user found for Stripe customer on subscription delete", customer_id=customer_id)
        return

    user.plan = "free"
    user.stripe_subscription_id = None
    await db.commit()

    logger.info("User downgraded to Free", user_id=str(user.id), customer_id=customer_id)


async def _on_subscription_updated(db: AsyncSession, subscription: dict) -> None:
    """
    customer.subscription.updated — sync plan based on subscription status.
    Active → premium; canceled/unpaid → free.
    """
    customer_id: str | None = subscription.get("customer")
    sub_status: str = subscription.get("status", "")
    sub_id: str | None = subscription.get("id")
    if not customer_id:
        return

    result = await db.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        return

    if sub_status in ("active", "trialing"):
        user.plan = "premium"
        user.stripe_subscription_id = sub_id
    elif sub_status in ("canceled", "unpaid", "incomplete_expired"):
        user.plan = "free"
        user.stripe_subscription_id = None

    await db.commit()
    logger.info(
        "Subscription updated",
        user_id=str(user.id),
        status=sub_status,
        plan=user.plan,
    )


async def _on_payment_failed(db: AsyncSession, invoice: dict) -> None:
    """
    invoice.payment_failed — log the event; plan stays premium during grace period.
    In production you would send a dunning email here.
    """
    customer_id: str | None = invoice.get("customer")
    logger.warning(
        "Invoice payment failed — user in grace period",
        customer_id=customer_id,
    )

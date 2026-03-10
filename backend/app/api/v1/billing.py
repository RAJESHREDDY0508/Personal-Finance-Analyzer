"""
Billing router — Stripe integration.

GET  /billing/plans        → list free / premium plan details (public)
POST /billing/checkout     → create Stripe Checkout session → redirect URL
POST /billing/portal       → create Stripe Billing Portal session → redirect URL
POST /billing/webhook      → Stripe webhook receiver (no JWT auth)
GET  /billing/subscription → current subscription status for the auth user
"""
from __future__ import annotations

import stripe
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.database import get_db
from app.models.user import User
from app.schemas.billing import (
    BillingPortalResponse,
    CheckoutResponse,
    PlanInfo,
    SubscriptionStatusResponse,
)
from app.services.billing_service import (
    PLANS,
    create_checkout_session,
    create_portal_session,
    get_subscription_status,
    handle_webhook_event,
    verify_webhook,
)

logger = structlog.get_logger(__name__)
router = APIRouter()


# ── GET /billing/plans ────────────────────────────────────────

@router.get("/plans", response_model=list[PlanInfo])
async def list_plans() -> list[PlanInfo]:
    """Return the available subscription plans (no auth required)."""
    return [PlanInfo(**p) for p in PLANS]


# ── POST /billing/checkout ────────────────────────────────────

@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(
    current_user: User = Depends(get_current_user),
) -> CheckoutResponse:
    """
    Create a Stripe Checkout session for the Premium plan.
    Returns a checkout URL to which the frontend should redirect the user.
    """
    success_url = f"{settings.frontend_url}/dashboard?checkout=success"
    cancel_url = f"{settings.frontend_url}/settings?checkout=cancelled"

    try:
        url = await create_checkout_session(current_user, success_url, cancel_url)
    except stripe.StripeError as exc:
        logger.error("Stripe checkout session creation failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment service temporarily unavailable",
        )

    return CheckoutResponse(checkout_url=url)


# ── POST /billing/portal ──────────────────────────────────────

@router.post("/portal", response_model=BillingPortalResponse)
async def create_portal(
    current_user: User = Depends(get_current_user),
) -> BillingPortalResponse:
    """
    Create a Stripe Billing Portal session so the user can manage their
    subscription, update payment methods, or view invoice history.
    """
    return_url = f"{settings.frontend_url}/settings"

    try:
        url = await create_portal_session(current_user, return_url)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except stripe.StripeError as exc:
        logger.error("Stripe portal session creation failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment service temporarily unavailable",
        )

    return BillingPortalResponse(portal_url=url)


# ── POST /billing/webhook ─────────────────────────────────────

@router.post("/webhook", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    stripe_signature: str = Header(alias="stripe-signature", default=""),
) -> dict:
    """
    Stripe webhook endpoint.
    No JWT auth — authentication is via Stripe-Signature header verification.
    Must receive the raw (un-parsed) request body for signature verification.
    """
    raw_body = await request.body()

    try:
        event = verify_webhook(raw_body, stripe_signature)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook payload",
        )
    except stripe.SignatureVerificationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Stripe signature",
        )

    await handle_webhook_event(db, event)
    return {"received": True}


# ── GET /billing/subscription ─────────────────────────────────

@router.get("/subscription", response_model=SubscriptionStatusResponse)
async def get_subscription(
    current_user: User = Depends(get_current_user),
) -> SubscriptionStatusResponse:
    """Return the current subscription plan and status for the authenticated user."""
    try:
        status_data = await get_subscription_status(current_user)
    except stripe.StripeError as exc:
        logger.error("Stripe subscription fetch failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment service temporarily unavailable",
        )

    return SubscriptionStatusResponse(**status_data)

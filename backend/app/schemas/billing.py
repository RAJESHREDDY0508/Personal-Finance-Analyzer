"""
Pydantic schemas for billing / Stripe endpoints.
"""
from pydantic import BaseModel


class CheckoutResponse(BaseModel):
    checkout_url: str


class BillingPortalResponse(BaseModel):
    portal_url: str


class SubscriptionStatusResponse(BaseModel):
    plan: str                   # free | premium
    status: str                 # active | canceled | past_due | none
    current_period_end: str | None


class PlanInfo(BaseModel):
    name: str
    price: float
    currency: str
    interval: str
    features: list[str]

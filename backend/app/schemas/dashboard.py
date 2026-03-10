"""
Pydantic schemas for dashboard endpoints.
"""
from decimal import Decimal

from pydantic import BaseModel

from app.schemas.transaction import SpendingTrendItem, TransactionSummaryItem


class DashboardOverview(BaseModel):
    health_score: int
    total_expenses_this_month: Decimal
    total_income_this_month: Decimal
    savings_rate: float          # percentage e.g. 23.5
    anomaly_count: int
    subscription_count: int


class SpendingByCategoryResponse(BaseModel):
    month: str
    categories: list[TransactionSummaryItem]


class SpendingTrendResponse(BaseModel):
    months: list[SpendingTrendItem]


class SavingsRateResponse(BaseModel):
    current_month_rate: float
    average_3_month_rate: float
    trend: str       # "up" | "down" | "stable"

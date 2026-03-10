"""
Pydantic schemas for transaction endpoints.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class TransactionResponse(BaseModel):
    id: uuid.UUID
    date: date
    description: str
    amount: Decimal
    category: str | None
    subcategory: str | None
    is_income: bool
    categorization_source: str | None
    user_category: str | None
    is_anomaly: bool
    anomaly_score: Decimal | None
    anomaly_reason: str | None
    is_duplicate: bool
    duplicate_of: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class UpdateCategoryRequest(BaseModel):
    category: str


class TransactionSummaryItem(BaseModel):
    category: str
    total: Decimal
    count: int
    percentage: float


class SpendingTrendItem(BaseModel):
    month: str      # "2025-01"
    total: Decimal

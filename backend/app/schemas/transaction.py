"""
Pydantic schemas for transaction endpoints.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, field_serializer, field_validator

from app.services.ai_service import CATEGORIES


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

    @field_serializer("amount", "anomaly_score")
    def serialize_decimal(self, v: Decimal | None) -> str | None:
        """Serialize Decimal as string to avoid float precision loss in JSON."""
        return str(v) if v is not None else None


class UpdateCategoryRequest(BaseModel):
    category: str

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        if v not in CATEGORIES:
            raise ValueError(f"Invalid category '{v}'. Must be one of: {', '.join(CATEGORIES)}")
        return v


class TransactionSummaryItem(BaseModel):
    category: str
    total: Decimal
    count: int
    percentage: float


class SpendingTrendItem(BaseModel):
    month: str      # "2025-01"
    total: Decimal

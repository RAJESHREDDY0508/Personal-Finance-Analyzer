"""
Pydantic schemas for budget endpoints.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class BudgetCreate(BaseModel):
    category: str = Field(..., min_length=1, max_length=100)
    month: date       # caller passes first day of month; normalised server-side
    monthly_limit: Decimal = Field(..., ge=0)


class BudgetResponse(BaseModel):
    id: uuid.UUID
    category: str
    month: date
    monthly_limit: Decimal | None
    predicted_spend: Decimal | None
    ml_confidence: Decimal | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BudgetPrediction(BaseModel):
    category: str
    month: date              # first day of the predicted month
    predicted_spend: float
    ml_confidence: float
    prediction_method: str   # "linear_regression" | "moving_average"


class BudgetVsActualItem(BaseModel):
    category: str
    month: str
    monthly_limit: float | None
    predicted_spend: float | None
    actual_spend: float
    variance: float          # actual − predicted/limit (positive = over)
    variance_pct: float


class BudgetVsActualResponse(BaseModel):
    month: str
    items: list[BudgetVsActualItem]


class PredictionsResponse(BaseModel):
    predictions: list[BudgetPrediction]
    count: int

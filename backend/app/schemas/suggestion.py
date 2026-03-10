"""
Pydantic schemas for savings suggestion endpoints.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class SuggestionResponse(BaseModel):
    id: uuid.UUID
    suggestion_type: str
    category: str | None
    description: str
    estimated_savings: Decimal | None
    dismissed: bool
    generated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SuggestionsListResponse(BaseModel):
    suggestions: list[SuggestionResponse]
    total: int


class GenerateSuggestionsResponse(BaseModel):
    generated: int
    message: str

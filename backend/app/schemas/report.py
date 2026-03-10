"""
Pydantic schemas for monthly report endpoints.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


class ReportOut(BaseModel):
    id: uuid.UUID
    report_month: date
    email_sent: bool
    email_sent_at: datetime | None = None
    total_income: Decimal | None = None
    total_expenses: Decimal | None = None
    savings_rate: Decimal | None = None
    health_score: int | None = None
    generated_at: datetime
    has_file: bool = False

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _set_has_file(cls, values):
        if hasattr(values, "s3_key"):
            values.__dict__["has_file"] = bool(values.s3_key)
        elif isinstance(values, dict):
            values["has_file"] = bool(values.get("s3_key"))
        return values


class GenerateReportRequest(BaseModel):
    year: int | None = Field(default=None, ge=2000, le=2100)
    month: int | None = Field(default=None, ge=1, le=12)


class DownloadUrlOut(BaseModel):
    download_url: str
    expires_in: int = 3600

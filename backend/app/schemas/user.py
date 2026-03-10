"""
Pydantic schemas for user endpoints.
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    plan: str
    health_score: int
    email_reports: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UpdateUserRequest(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    email_reports: bool | None = None

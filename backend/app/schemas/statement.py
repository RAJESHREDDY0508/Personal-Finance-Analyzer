"""
Pydantic schemas for bank statement endpoints.
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# ── Request schemas ───────────────────────────────────────────

class StatementUploadRequest(BaseModel):
    file_name: str = Field(..., min_length=1, max_length=255)
    file_type: str = Field(..., pattern=r"^(csv|pdf)$")


# ── Response schemas ──────────────────────────────────────────

class StatementUploadResponse(BaseModel):
    statement_id: uuid.UUID
    upload_url: str          # Pre-signed S3 POST URL
    upload_fields: dict      # Fields to include in the multipart POST form
    s3_key: str
    message: str = "Upload the file to upload_url with the provided upload_fields."


class StatementResponse(BaseModel):
    id: uuid.UUID
    file_name: str
    file_type: str
    status: str
    row_count: int | None
    error_message: str | None
    uploaded_at: datetime
    processed_at: datetime | None

    model_config = {"from_attributes": True}


class StatementListResponse(BaseModel):
    statements: list[StatementResponse]
    total: int

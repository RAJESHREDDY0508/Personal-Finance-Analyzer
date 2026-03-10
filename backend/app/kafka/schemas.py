"""
Pydantic models for Kafka message payloads.
Used for validation when producing and consuming messages.
"""
import uuid
from datetime import datetime

from pydantic import BaseModel


class StatementUploadedEvent(BaseModel):
    statement_id: uuid.UUID
    user_id: uuid.UUID
    s3_key: str
    file_type: str          # csv | pdf
    uploaded_at: datetime


class StatementParsedEvent(BaseModel):
    statement_id: uuid.UUID
    user_id: uuid.UUID
    transaction_ids: list[uuid.UUID]
    row_count: int


class TransactionsCategorizedEvent(BaseModel):
    user_id: uuid.UUID
    statement_id: uuid.UUID
    categorized_count: int
    anomaly_check_needed: bool = True


class AnomaliesDetectedEvent(BaseModel):
    user_id: uuid.UUID
    anomaly_transaction_ids: list[uuid.UUID]
    duplicate_transaction_ids: list[uuid.UUID]


class ReportScheduleEvent(BaseModel):
    user_id: uuid.UUID
    report_month: str       # "YYYY-MM"
    trigger: str            # cron | manual


class SubscriptionEvent(BaseModel):
    user_id: uuid.UUID
    stripe_event_id: str
    event_type: str
    new_plan: str           # free | premium

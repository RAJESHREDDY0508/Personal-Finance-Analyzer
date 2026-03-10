"""
Report generator worker.
Consumes: report.schedule
Publishes: report.generated

Payload schema (report.schedule):
  {
    "user_id": "<uuid>",
    "year":    2025,
    "month":   1
  }
"""
from __future__ import annotations

import uuid
from datetime import date

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.kafka.producer import kafka_producer
from app.kafka.topics import Topics
from app.models.user import User
from app.services.report_service import generate_monthly_report
from app.workers.base_worker import BaseWorker

logger = structlog.get_logger(__name__)


class ReportGeneratorWorker(BaseWorker):
    topic = Topics.REPORT_SCHEDULE
    group_id = "report-generator-group"

    async def process_message(self, payload: dict) -> None:
        user_id = uuid.UUID(str(payload["user_id"]))

        today = date.today()
        # Default to the previous calendar month
        if today.month == 1:
            default_year, default_month = today.year - 1, 12
        else:
            default_year, default_month = today.year, today.month - 1

        year = int(payload.get("year") or default_year)
        month = int(payload.get("month") or default_month)

        engine = create_async_engine(settings.database_url)
        SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

        try:
            async with SessionLocal() as db:
                # Fetch user to pass name + verify existence
                user_result = await db.execute(
                    select(User).where(User.id == user_id)
                )
                user = user_result.scalar_one_or_none()
                if user is None:
                    logger.warning(
                        "Report generation skipped — user not found",
                        user_id=str(user_id),
                    )
                    return

                report = await generate_monthly_report(
                    db=db,
                    user_id=user_id,
                    year=year,
                    month=month,
                    user_name=user.full_name,
                )

            # Publish to report.generated so email sender picks it up
            await kafka_producer.send(
                Topics.REPORT_GENERATED,
                payload={
                    "user_id": str(user_id),
                    "report_id": str(report.id),
                    "year": year,
                    "month": month,
                    "user_email": user.email,
                    "user_name": user.full_name,
                    "s3_key": report.s3_key,
                },
                key=str(user_id),
            )
            logger.info(
                "Report generated — report.generated event published",
                user_id=str(user_id),
                report_id=str(report.id),
                month=f"{year}-{month:02d}",
            )
        finally:
            await engine.dispose()

"""
Email sender worker.
Consumes: report.generated (SQS)

Payload schema (report.generated):
  {
    "user_id":    "<uuid>",
    "report_id":  "<uuid>",
    "year":       2025,
    "month":      1,
    "user_email": "user@example.com",
    "user_name":  "Jane Doe",        # nullable
    "s3_key":     "reports/..."      # nullable
  }
"""
from __future__ import annotations

import uuid
from datetime import date

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.sqs.queues import Queues
from app.models.report import MonthlyReport
from app.models.user import User
from app.services.analytics_service import get_dashboard_overview, get_spending_by_category
from app.services.email_service import send_monthly_report_email
from app.services.report_service import _get_report_presigned_url, mark_email_sent
from app.workers.base_worker import BaseWorker

logger = structlog.get_logger(__name__)


class EmailSenderWorker(BaseWorker):
    queue_url_fn = Queues.report_generated

    async def process_message(self, payload: dict) -> None:
        user_id = uuid.UUID(str(payload["user_id"]))
        report_id = uuid.UUID(str(payload["report_id"]))
        year = int(payload["year"])
        month = int(payload["month"])
        user_email: str = payload["user_email"]
        user_name: str | None = payload.get("user_name")
        s3_key: str | None = payload.get("s3_key")

        engine = create_async_engine(settings.database_url)
        SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

        try:
            async with SessionLocal() as db:
                # Verify user has email_reports enabled
                user_result = await db.execute(
                    select(User).where(User.id == user_id)
                )
                user = user_result.scalar_one_or_none()
                if user is None or not user.email_reports:
                    logger.info(
                        "Email send skipped",
                        user_id=str(user_id),
                        reason="user not found or email_reports disabled",
                    )
                    return

                month_name = date(year, month, 1).strftime("%B %Y")
                overview = await get_dashboard_overview(db, user_id, year, month)
                by_category = await get_spending_by_category(db, user_id, year, month)

                # Generate presigned download URL if file is available
                download_url: str | None = None
                if s3_key:
                    try:
                        download_url = await _get_report_presigned_url(s3_key)
                    except Exception as exc:
                        logger.warning(
                            "Could not generate download URL — sending without link",
                            error=str(exc),
                            s3_key=s3_key,
                        )

                health_score = user.health_score or 0

                await send_monthly_report_email(
                    to_email=user_email,
                    user_name=user_name,
                    month_name=month_name,
                    overview=overview,
                    by_category=by_category,
                    health_score=health_score,
                    download_url=download_url,
                )

                # Mark the MonthlyReport row as sent
                report_result = await db.execute(
                    select(MonthlyReport).where(
                        and_(
                            MonthlyReport.id == report_id,
                            MonthlyReport.user_id == user_id,
                        )
                    )
                )
                report = report_result.scalar_one_or_none()
                if report:
                    await mark_email_sent(db, report)

                logger.info(
                    "Monthly report email delivered",
                    user_id=str(user_id),
                    report_id=str(report_id),
                    month=f"{year}-{month:02d}",
                )
        finally:
            await engine.dispose()

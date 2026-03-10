"""
Report service — monthly financial report generation.

Aggregates analytics data, renders the Jinja2 HTML template,
uploads the rendered HTML to S3, and upserts the MonthlyReport DB record.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import boto3
import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.report import MonthlyReport
from app.models.transaction import Transaction
from app.services.analytics_service import (
    get_dashboard_overview,
    get_savings_rate,
    get_spending_by_category,
)
from app.utils.health_score import compute_health_score

logger = structlog.get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)


# ── S3 helpers ────────────────────────────────────────────────

def _get_s3_client():
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )


async def _upload_report_html(html: str, s3_key: str) -> None:
    """Upload rendered HTML to the reports S3 bucket."""
    client = _get_s3_client()
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: client.put_object(
            Bucket=settings.s3_reports_bucket,
            Key=s3_key,
            Body=html.encode("utf-8"),
            ContentType="text/html; charset=utf-8",
        ),
    )
    logger.info("Report HTML uploaded to S3", key=s3_key)


async def _get_report_presigned_url(s3_key: str) -> str:
    """Generate a presigned GET URL for a report in the reports bucket."""
    client = _get_s3_client()
    loop = asyncio.get_event_loop()
    url: str = await loop.run_in_executor(
        None,
        lambda: client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_reports_bucket, "Key": s3_key},
            ExpiresIn=settings.s3_presigned_url_expiry,
        ),
    )
    return url


# ── Core generation ───────────────────────────────────────────

async def generate_monthly_report(
    db: AsyncSession,
    user_id: uuid.UUID,
    year: int,
    month: int,
    user_name: str | None = None,
) -> MonthlyReport:
    """
    Generate (or regenerate) a monthly financial report for one user.

    Steps:
      1. Aggregate analytics via existing services
      2. Compute health score
      3. Render Jinja2 HTML template
      4. Upload HTML to S3 (non-fatal if AWS unavailable in dev)
      5. Upsert the MonthlyReport row and return it
    """
    report_month = date(year, month, 1)
    month_name = report_month.strftime("%B %Y")

    # 1. Analytics aggregation
    overview = await get_dashboard_overview(db, user_id, year, month)
    by_category = await get_spending_by_category(db, user_id, year, month)

    # 2. Health score
    total_txn_result = await db.execute(
        select(func.count()).where(
            and_(
                Transaction.user_id == user_id,
                Transaction.is_duplicate == False,  # noqa: E712
            )
        )
    )
    total_transactions = total_txn_result.scalar() or 0
    health = compute_health_score(
        income=overview["income"],
        expenses=overview["expenses"],
        category_count=len(by_category),
        anomaly_count=overview["anomaly_count"],
        total_transactions=total_transactions,
    )

    # 3. Render Jinja2 template
    template = _jinja_env.get_template("email/monthly_report.html")
    html = template.render(
        user_name=user_name,
        month_name=month_name,
        overview=overview,
        by_category=by_category[:8],
        health_score=health,
        download_url=None,          # populated after S3 upload
        frontend_url=settings.frontend_url,
    )

    # 4. Upload to S3
    s3_key = f"reports/{user_id}/{year}-{month:02d}/report.html"
    s3_key_stored: str | None = None
    try:
        await _upload_report_html(html, s3_key)
        s3_key_stored = s3_key
    except Exception as exc:
        logger.warning(
            "S3 upload failed — report stored in DB without file",
            error=str(exc),
            key=s3_key,
        )

    # 5. Upsert MonthlyReport
    existing = await db.execute(
        select(MonthlyReport).where(
            and_(
                MonthlyReport.user_id == user_id,
                MonthlyReport.report_month == report_month,
            )
        )
    )
    report = existing.scalar_one_or_none()
    if report is None:
        report = MonthlyReport(user_id=user_id, report_month=report_month)
        db.add(report)

    report.s3_key = s3_key_stored
    report.total_income = Decimal(str(round(overview["income"], 2)))
    report.total_expenses = Decimal(str(round(overview["expenses"], 2)))
    report.savings_rate = Decimal(str(round(overview["savings_rate"], 4)))
    report.health_score = health

    await db.commit()
    await db.refresh(report)

    logger.info(
        "Monthly report generated",
        user_id=str(user_id),
        month=f"{year}-{month:02d}",
        report_id=str(report.id),
        health_score=health,
    )
    return report


# ── Query helpers ─────────────────────────────────────────────

async def get_user_reports(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[MonthlyReport]:
    """Return all reports for a user, newest month first."""
    result = await db.execute(
        select(MonthlyReport)
        .where(MonthlyReport.user_id == user_id)
        .order_by(MonthlyReport.report_month.desc())
    )
    return list(result.scalars().all())


async def get_report_download_url(
    db: AsyncSession,
    report_id: uuid.UUID,
    user_id: uuid.UUID,
) -> str:
    """
    Return a presigned S3 download URL for the given report.
    Raises ValueError if not found, not owned, or no file available.
    """
    result = await db.execute(
        select(MonthlyReport).where(
            and_(
                MonthlyReport.id == report_id,
                MonthlyReport.user_id == user_id,
            )
        )
    )
    report = result.scalar_one_or_none()
    if report is None:
        raise ValueError("Report not found")
    if not report.s3_key:
        raise ValueError("Report file not yet available")

    return await _get_report_presigned_url(report.s3_key)


async def mark_email_sent(
    db: AsyncSession,
    report: MonthlyReport,
) -> None:
    """Update the report record to reflect a successful email delivery."""
    from datetime import datetime, timezone
    report.email_sent = True
    report.email_sent_at = datetime.now(timezone.utc)
    await db.commit()

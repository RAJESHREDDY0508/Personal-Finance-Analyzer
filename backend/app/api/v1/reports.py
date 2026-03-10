"""
Reports router — monthly financial report endpoints.

GET  /reports/              → list user's reports
GET  /reports/{id}/download → presigned S3 download URL
POST /reports/generate      → trigger report generation for a given month
POST /reports/{id}/resend   → re-send email for an existing report
"""
from __future__ import annotations

import uuid
from datetime import date

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.report import MonthlyReport
from app.models.user import User
from app.schemas.report import DownloadUrlOut, GenerateReportRequest, ReportOut
from app.services.analytics_service import get_dashboard_overview, get_spending_by_category
from app.services.email_service import send_monthly_report_email
from app.services.report_service import (
    _get_report_presigned_url,
    generate_monthly_report,
    get_report_download_url,
    get_user_reports,
    mark_email_sent,
)

logger = structlog.get_logger(__name__)
router = APIRouter()


# ── List reports ──────────────────────────────────────────────

@router.get("/", response_model=list[ReportOut])
async def list_reports(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all monthly reports for the authenticated user, newest first."""
    return await get_user_reports(db, current_user.id)


# ── Download URL ──────────────────────────────────────────────

@router.get("/{report_id}/download", response_model=DownloadUrlOut)
async def download_report(
    report_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a presigned S3 URL to download the HTML report file."""
    try:
        url = await get_report_download_url(db, report_id, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.error("Failed to generate report download URL", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not generate download URL",
        )
    return DownloadUrlOut(download_url=url)


# ── Generate ──────────────────────────────────────────────────

@router.post("/generate", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
async def generate_report(
    body: GenerateReportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger on-demand report generation for a specific month.
    Defaults to the previous calendar month if year/month not specified.
    """
    today = date.today()
    if today.month == 1:
        default_year, default_month = today.year - 1, 12
    else:
        default_year, default_month = today.year, today.month - 1

    year = body.year or default_year
    month = body.month or default_month

    try:
        report = await generate_monthly_report(
            db=db,
            user_id=current_user.id,
            year=year,
            month=month,
            user_name=current_user.full_name,
        )
    except Exception as exc:
        logger.error("Report generation failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Report generation failed",
        )

    return report


# ── Re-send email ─────────────────────────────────────────────

@router.post("/{report_id}/resend", status_code=status.HTTP_202_ACCEPTED)
async def resend_report_email(
    report_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-deliver the email for an already-generated report."""
    result = await db.execute(
        select(MonthlyReport).where(
            and_(
                MonthlyReport.id == report_id,
                MonthlyReport.user_id == current_user.id,
            )
        )
    )
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")

    year = report.report_month.year
    month = report.report_month.month
    month_name = report.report_month.strftime("%B %Y")

    overview = await get_dashboard_overview(db, current_user.id, year, month)
    by_category = await get_spending_by_category(db, current_user.id, year, month)

    download_url: str | None = None
    if report.s3_key:
        try:
            download_url = await _get_report_presigned_url(report.s3_key)
        except Exception:
            pass

    try:
        await send_monthly_report_email(
            to_email=current_user.email,
            user_name=current_user.full_name,
            month_name=month_name,
            overview=overview,
            by_category=by_category,
            health_score=report.health_score or 0,
            download_url=download_url,
        )
        await mark_email_sent(db, report)
    except Exception as exc:
        logger.error("Report email re-send failed", report_id=str(report_id), error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email delivery failed",
        )

    return {"message": f"Report email re-sent for {month_name}"}

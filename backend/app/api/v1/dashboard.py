"""
Dashboard router — aggregated financial analytics.
"""
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.analytics_service import (
    get_dashboard_overview,
    get_savings_rate,
    get_spending_by_category,
    get_spending_trend,
)

router = APIRouter()


@router.get("/overview", summary="Monthly income, expenses, net, savings rate")
async def dashboard_overview(
    year: int = Query(default=None),
    month: int = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    today = date.today()
    y = year or today.year
    m = month or today.month
    return await get_dashboard_overview(db, current_user.id, y, m)


@router.get("/spending-by-category", summary="Expenses grouped by category for a month")
async def spending_by_category(
    year: int = Query(default=None),
    month: int = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    today = date.today()
    y = year or today.year
    m = month or today.month
    categories = await get_spending_by_category(db, current_user.id, y, m)
    return {"year": y, "month": m, "categories": categories}


@router.get("/spending-trend", summary="Monthly expense trend for the last N months")
async def spending_trend(
    months: int = Query(default=6, ge=1, le=24),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    trend = await get_spending_trend(db, current_user.id, months)
    return {"trend": trend}


@router.get("/savings-rate", summary="Monthly savings rate trend")
async def savings_rate(
    months: int = Query(default=6, ge=1, le=24),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    trend = await get_savings_rate(db, current_user.id, months)
    return {"trend": trend}

"""
Analytics service — aggregate queries for dashboard endpoints.

All heavy SQL runs in the async session; results are returned as plain dicts
and serialised by the API layer.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import structlog
from sqlalchemy import func, select, and_, extract, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction
from app.utils.health_score import compute_health_score

logger = structlog.get_logger(__name__)


# ── Dashboard overview ────────────────────────────────────────

async def get_dashboard_overview(
    db: AsyncSession,
    user_id: uuid.UUID,
    year: int,
    month: int,
) -> dict:
    """
    Returns income, expenses, net, savings_rate, and top anomaly count
    for the given calendar month.
    """
    month_start = date(year, month, 1)
    # last day of month
    if month == 12:
        month_end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        month_end = date(year, month + 1, 1) - timedelta(days=1)

    result = await db.execute(
        select(
            func.sum(case((Transaction.is_income == True, Transaction.amount), else_=Decimal("0"))).label("income"),  # noqa: E712
            func.sum(case((Transaction.is_income == False, Transaction.amount), else_=Decimal("0"))).label("expenses"),  # noqa: E712
            func.count(case((Transaction.is_anomaly == True, 1))).label("anomaly_count"),  # noqa: E712
        ).where(
            and_(
                Transaction.user_id == user_id,
                Transaction.date >= month_start,
                Transaction.date <= month_end,
                Transaction.is_duplicate == False,  # noqa: E712
            )
        )
    )
    row = result.one()
    income = row.income or Decimal("0")
    expenses = abs(row.expenses or Decimal("0"))   # expenses are stored negative
    net = income - expenses
    savings_rate = float(net / income) if income > 0 else 0.0

    return {
        "month": f"{year}-{month:02d}",
        "income": float(income),
        "expenses": float(expenses),
        "net": float(net),
        "savings_rate": round(savings_rate, 4),
        "anomaly_count": int(row.anomaly_count or 0),
    }


# ── Spending by category ──────────────────────────────────────

async def get_spending_by_category(
    db: AsyncSession,
    user_id: uuid.UUID,
    year: int,
    month: int,
) -> list[dict]:
    """
    Returns spending per category sorted by total (descending).
    Excludes income transactions.
    """
    month_start = date(year, month, 1)
    if month == 12:
        month_end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        month_end = date(year, month + 1, 1) - timedelta(days=1)

    result = await db.execute(
        select(
            Transaction.category,
            func.sum(Transaction.amount).label("total"),
            func.count().label("count"),
        )
        .where(
            and_(
                Transaction.user_id == user_id,
                Transaction.is_income == False,  # noqa: E712
                Transaction.is_duplicate == False,  # noqa: E712
                Transaction.date >= month_start,
                Transaction.date <= month_end,
            )
        )
        .group_by(Transaction.category)
        .order_by(func.sum(Transaction.amount))   # most negative = highest spend
    )

    rows = result.all()
    grand_total = sum(abs(r.total) for r in rows) or Decimal("1")

    return [
        {
            "category": r.category or "Uncategorized",
            "total": float(abs(r.total)),
            "count": int(r.count),
            "percentage": round(float(abs(r.total) / grand_total * 100), 2),
        }
        for r in rows
    ]


# ── Spending trend (last N months) ───────────────────────────

async def get_spending_trend(
    db: AsyncSession,
    user_id: uuid.UUID,
    months: int = 6,
) -> list[dict]:
    """
    Returns monthly total expenses for the last `months` months.
    """
    today = date.today()
    start = date(today.year, today.month, 1)
    for _ in range(months - 1):
        start = (start - timedelta(days=1)).replace(day=1)

    result = await db.execute(
        select(
            extract("year", Transaction.date).label("year"),
            extract("month", Transaction.date).label("month"),
            func.sum(Transaction.amount).label("total"),
        )
        .where(
            and_(
                Transaction.user_id == user_id,
                Transaction.is_income == False,  # noqa: E712
                Transaction.is_duplicate == False,  # noqa: E712
                Transaction.date >= start,
            )
        )
        .group_by("year", "month")
        .order_by("year", "month")
    )

    return [
        {
            "month": f"{int(r.year)}-{int(r.month):02d}",
            "total": float(abs(r.total)),
        }
        for r in result.all()
    ]


# ── Savings rate trend ────────────────────────────────────────

async def get_savings_rate(
    db: AsyncSession,
    user_id: uuid.UUID,
    months: int = 6,
) -> list[dict]:
    """Monthly savings rate (net / income) for the last N months."""
    today = date.today()
    start = date(today.year, today.month, 1)
    for _ in range(months - 1):
        start = (start - timedelta(days=1)).replace(day=1)

    result = await db.execute(
        select(
            extract("year", Transaction.date).label("year"),
            extract("month", Transaction.date).label("month"),
            func.sum(case((Transaction.is_income == True, Transaction.amount), else_=Decimal("0"))).label("income"),  # noqa: E712
            func.sum(case((Transaction.is_income == False, Transaction.amount), else_=Decimal("0"))).label("expenses"),  # noqa: E712
        )
        .where(
            and_(
                Transaction.user_id == user_id,
                Transaction.is_duplicate == False,  # noqa: E712
                Transaction.date >= start,
            )
        )
        .group_by("year", "month")
        .order_by("year", "month")
    )

    trend = []
    for r in result.all():
        income = float(r.income or 0)
        expenses = abs(float(r.expenses or 0))
        net = income - expenses
        savings_rate = round(net / income, 4) if income > 0 else 0.0
        trend.append({
            "month": f"{int(r.year)}-{int(r.month):02d}",
            "income": income,
            "expenses": expenses,
            "savings_rate": savings_rate,
        })

    return trend

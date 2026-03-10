"""
Budgets router.

Endpoints:
  GET    /budgets/              — list budgets for a given month
  POST   /budgets/              — set/update a monthly spending limit
  GET    /budgets/predictions   — ML-predicted spending for next month
  GET    /budgets/vs-actual     — budget limits + predictions vs actual spend
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.budget import Budget
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.budget import (
    BudgetCreate,
    BudgetPrediction,
    BudgetResponse,
    BudgetVsActualItem,
    BudgetVsActualResponse,
    PredictionsResponse,
)
from app.services.ml_service import predict_spending_for_user

router = APIRouter()


# ── GET /budgets/ ──────────────────────────────────────────────

@router.get("/", response_model=list[BudgetResponse])
async def list_budgets(
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Budget]:
    today = date.today()
    y = year or today.year
    m = month or today.month
    month_date = date(y, m, 1)

    result = await db.execute(
        select(Budget)
        .where(and_(Budget.user_id == current_user.id, Budget.month == month_date))
        .order_by(Budget.category)
    )
    return list(result.scalars().all())


# ── POST /budgets/ ─────────────────────────────────────────────

@router.post("/", response_model=BudgetResponse, status_code=status.HTTP_201_CREATED)
async def set_budget(
    body: BudgetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Budget:
    """Create or update a monthly spending limit for a category."""
    month = body.month.replace(day=1)   # normalise to first of month

    result = await db.execute(
        select(Budget).where(
            and_(
                Budget.user_id == current_user.id,
                Budget.category == body.category,
                Budget.month == month,
            )
        )
    )
    budget = result.scalar_one_or_none()

    if budget is None:
        budget = Budget(
            user_id=current_user.id,
            category=body.category,
            month=month,
            monthly_limit=body.monthly_limit,
        )
        db.add(budget)
    else:
        budget.monthly_limit = body.monthly_limit

    await db.commit()
    await db.refresh(budget)
    return budget


# ── GET /budgets/predictions ───────────────────────────────────

@router.get("/predictions", response_model=PredictionsResponse)
async def get_budget_predictions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Run ML predictor and return next-month spending predictions per category."""
    predictions = await predict_spending_for_user(db, current_user.id)
    return {
        "predictions": [
            BudgetPrediction(
                category=p["category"],
                month=p["month"],
                predicted_spend=p["predicted_spend"],
                ml_confidence=p["ml_confidence"],
                prediction_method=p["prediction_method"],
            )
            for p in predictions
        ],
        "count": len(predictions),
    }


# ── GET /budgets/vs-actual ─────────────────────────────────────

@router.get("/vs-actual", response_model=BudgetVsActualResponse)
async def get_budget_vs_actual(
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Compare budget limits + ML predictions against actual spending."""
    today = date.today()
    y = year or today.year
    m = month or today.month
    month_date = date(y, m, 1)
    if m == 12:
        month_end = date(y + 1, 1, 1) - timedelta(days=1)
    else:
        month_end = date(y, m + 1, 1) - timedelta(days=1)

    # Actual spending per category
    actual_result = await db.execute(
        select(
            Transaction.category,
            func.sum(Transaction.amount).label("total"),
        )
        .where(
            and_(
                Transaction.user_id == current_user.id,
                Transaction.is_income == False,             # noqa: E712
                Transaction.is_duplicate == False,          # noqa: E712
                Transaction.date >= month_date,
                Transaction.date <= month_end,
            )
        )
        .group_by(Transaction.category)
    )
    actual_by_cat: dict[str, float] = {
        r.category: abs(float(r.total))
        for r in actual_result.all()
        if r.category
    }

    # Budget rows for this month
    budget_result = await db.execute(
        select(Budget).where(
            and_(Budget.user_id == current_user.id, Budget.month == month_date)
        )
    )
    budgets_by_cat: dict[str, Budget] = {
        b.category: b for b in budget_result.scalars().all()
    }

    all_cats: set[str] = set(actual_by_cat) | set(budgets_by_cat)
    items: list[BudgetVsActualItem] = []

    for cat in sorted(all_cats):
        actual = actual_by_cat.get(cat, 0.0)
        budget = budgets_by_cat.get(cat)
        predicted = float(budget.predicted_spend) if budget and budget.predicted_spend else None
        limit = float(budget.monthly_limit) if budget and budget.monthly_limit else None

        reference = predicted or limit or 0.0
        variance = actual - reference
        variance_pct = (variance / reference * 100) if reference > 0 else 0.0

        items.append(
            BudgetVsActualItem(
                category=cat,
                month=f"{y}-{m:02d}",
                monthly_limit=limit,
                predicted_spend=predicted,
                actual_spend=actual,
                variance=round(variance, 2),
                variance_pct=round(variance_pct, 2),
            )
        )

    return BudgetVsActualResponse(month=f"{y}-{m:02d}", items=items)

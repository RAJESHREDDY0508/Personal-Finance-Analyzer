"""
ML service — scikit-learn budget predictions per category.

Algorithm:
  - Collect last LOOKBACK_MONTHS months of expense totals per category.
  - If >= MIN_MONTHS_FOR_REGRESSION months of data: fit LinearRegression,
    predict next month's spend; confidence = max(0, R²).
  - Fallback (< 2 months): use simple moving average; confidence = 0.3–0.5.
  - Upsert predictions into the `budgets` table for `target_month`.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import structlog
from sqlalchemy import and_, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import Budget
from app.models.transaction import Transaction

logger = structlog.get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────

MIN_MONTHS_FOR_REGRESSION = 2
LOOKBACK_MONTHS = 6


# ── Helpers ───────────────────────────────────────────────────

def _next_month_start(ref: date | None = None) -> date:
    """Return the first calendar day of the month after `ref`."""
    ref = ref or date.today()
    if ref.month == 12:
        return date(ref.year + 1, 1, 1)
    return date(ref.year, ref.month + 1, 1)


def _months_ago_start(n: int, ref: date | None = None) -> date:
    """Return the first day of the month `n` months before `ref`."""
    ref = ref or date.today()
    y, m = ref.year, ref.month - n
    while m <= 0:
        y -= 1
        m += 12
    return date(y, m, 1)


def _linear_regression_predict(x_vals: list[int], y_vals: list[float]) -> tuple[float, float]:
    """
    Synchronous helper — safe to run in an executor thread.
    Returns (predicted_value_for_next_point, confidence_r2_clamped_0_1).
    """
    import numpy as np  # noqa: PLC0415
    from sklearn.linear_model import LinearRegression  # noqa: PLC0415

    X = np.array(x_vals, dtype=float).reshape(-1, 1)
    y = np.array(y_vals, dtype=float)
    model = LinearRegression()
    model.fit(X, y)

    next_x = np.array([[float(len(x_vals))]])
    prediction = float(model.predict(next_x)[0])

    r2 = float(model.score(X, y))
    confidence = max(0.0, min(1.0, r2))

    return max(0.0, prediction), confidence


# ── Main service function ──────────────────────────────────────

async def predict_spending_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    target_month: date | None = None,
) -> list[dict]:
    """
    Predict next-month spending per category and upsert into `budgets`.

    Returns a list of prediction dicts:
      {category, month, predicted_spend, ml_confidence, prediction_method}
    """
    import asyncio  # noqa: PLC0415

    target_month = target_month or _next_month_start()
    cutoff = _months_ago_start(LOOKBACK_MONTHS)

    # ── 1. Query monthly spending per category ────────────────────
    result = await db.execute(
        select(
            Transaction.category,
            extract("year",  Transaction.date).label("yr"),
            extract("month", Transaction.date).label("mo"),
            func.sum(Transaction.amount).label("total"),
        )
        .where(
            and_(
                Transaction.user_id == user_id,
                Transaction.is_income == False,   # noqa: E712
                Transaction.is_duplicate == False, # noqa: E712
                Transaction.category.is_not(None),
                Transaction.date >= cutoff,
            )
        )
        .group_by(Transaction.category, "yr", "mo")
        .order_by(Transaction.category, "yr", "mo")
    )
    rows = result.all()

    if not rows:
        return []

    # ── 2. Organise into per-category time-series ─────────────────
    # Build a global sorted month list → consistent indices across categories
    all_months: list[tuple[int, int]] = sorted(
        set((int(r.yr), int(r.mo)) for r in rows)
    )
    month_to_idx = {ym: i for i, ym in enumerate(all_months)}

    from collections import defaultdict  # noqa: PLC0415
    category_series: dict[str, list[tuple[int, float]]] = defaultdict(list)

    for r in rows:
        ym = (int(r.yr), int(r.mo))
        idx = month_to_idx[ym]
        category_series[r.category].append((idx, abs(float(r.total))))

    # ── 3. Predict for each category ─────────────────────────────
    loop = asyncio.get_event_loop()
    predictions: list[dict] = []

    for category, series in category_series.items():
        series.sort(key=lambda t: t[0])
        x_vals = [t[0] for t in series]
        y_vals = [t[1] for t in series]
        n = len(x_vals)

        if n >= MIN_MONTHS_FOR_REGRESSION:
            try:
                predicted, confidence = await loop.run_in_executor(
                    None, _linear_regression_predict, x_vals, y_vals
                )
                method = "linear_regression"
            except Exception as exc:
                logger.warning("ml.regression_failed", category=category, error=str(exc))
                predicted = sum(y_vals[-3:]) / min(n, 3)
                confidence = 0.4
                method = "moving_average"
        else:
            # Simple moving average fallback
            predicted = sum(y_vals) / n
            confidence = 0.3 if n == 1 else 0.5
            method = "moving_average"

        predicted = max(0.0, predicted)

        predictions.append(
            {
                "category": category,
                "month": target_month,
                "predicted_spend": round(predicted, 2),
                "ml_confidence": round(confidence, 4),
                "prediction_method": method,
            }
        )

        await _upsert_budget_prediction(
            db, user_id, category, target_month,
            Decimal(str(round(predicted, 2))),
            Decimal(str(round(confidence, 4))),
        )

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    logger.info("ml.predictions_complete", user_id=str(user_id), count=len(predictions))
    return predictions


async def _upsert_budget_prediction(
    db: AsyncSession,
    user_id: uuid.UUID,
    category: str,
    month: date,
    predicted_spend: Decimal,
    ml_confidence: Decimal,
) -> None:
    """Insert or update the ML prediction columns in the budgets table."""
    result = await db.execute(
        select(Budget).where(
            and_(
                Budget.user_id == user_id,
                Budget.category == category,
                Budget.month == month,
            )
        )
    )
    budget = result.scalar_one_or_none()

    if budget is None:
        budget = Budget(
            user_id=user_id,
            category=category,
            month=month,
            predicted_spend=predicted_spend,
            ml_confidence=ml_confidence,
        )
        db.add(budget)
    else:
        budget.predicted_spend = predicted_spend
        budget.ml_confidence = ml_confidence

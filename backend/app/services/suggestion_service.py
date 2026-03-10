"""
Savings suggestion service.

Generates actionable financial recommendations by:
  1. Comparing actual vs predicted category spending (overspending alerts).
  2. Detecting recurring subscriptions (same description+amount ≥ 2 months).
  3. Surfacing high-anomaly-rate categories as spending reviews.

Suggestions are written to `savings_suggestions` (stale non-dismissed rows
are replaced on each run).
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal

import structlog
from sqlalchemy import and_, delete, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import Budget
from app.models.suggestion import SavingsSuggestion
from app.models.transaction import Transaction

logger = structlog.get_logger(__name__)

MAX_SUGGESTIONS = 10
OVERSPEND_THRESHOLD = 1.10   # flag if actual > 110 % of predicted
MIN_SUBSCRIPTION_MONTHS = 2  # same description+amount in N distinct months → subscription


# ── Helpers ───────────────────────────────────────────────────

def _prev_month_start(ref: date | None = None) -> date:
    ref = ref or date.today()
    if ref.month == 1:
        return date(ref.year - 1, 12, 1)
    return date(ref.year, ref.month - 1, 1)


def _month_start(ref: date | None = None) -> date:
    ref = ref or date.today()
    return date(ref.year, ref.month, 1)


def _months_ago(n: int, ref: date | None = None) -> date:
    ref = ref or date.today()
    y, m = ref.year, ref.month - n
    while m <= 0:
        y -= 1
        m += 12
    return date(y, m, 1)


# ── Core generator ────────────────────────────────────────────

async def generate_suggestions_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[dict]:
    """
    Analyse spending patterns and return a list of suggestion dicts.
    Stale non-dismissed suggestions for this user are deleted and replaced.
    """
    today = date.today()
    current_month = _month_start(today)
    prev_month = _prev_month_start(today)
    three_months_ago = _months_ago(3, today)

    # ── 1. Actual spending last complete month per category ────────
    actual_result = await db.execute(
        select(
            Transaction.category,
            func.sum(Transaction.amount).label("total"),
        )
        .where(
            and_(
                Transaction.user_id == user_id,
                Transaction.is_income == False,           # noqa: E712
                Transaction.is_duplicate == False,        # noqa: E712
                Transaction.category.is_not(None),
                Transaction.date >= prev_month,
                Transaction.date < current_month,
            )
        )
        .group_by(Transaction.category)
    )
    actual_by_cat: dict[str, float] = {
        r.category: abs(float(r.total)) for r in actual_result.all()
    }

    # ── 2. Predicted spending from budgets table ───────────────────
    budget_result = await db.execute(
        select(Budget).where(
            and_(
                Budget.user_id == user_id,
                Budget.month.in_([prev_month, current_month]),
            )
        )
    )
    predicted_by_cat: dict[str, float] = {
        b.category: float(b.predicted_spend)
        for b in budget_result.scalars().all()
        if b.predicted_spend is not None
    }

    raw_suggestions: list[dict] = []

    # ── 3a. Overspending suggestions ───────────────────────────────
    for category, actual in actual_by_cat.items():
        predicted = predicted_by_cat.get(category)
        if predicted and predicted > 0 and actual > predicted * OVERSPEND_THRESHOLD:
            overspend = actual - predicted
            desc = (
                f"You spent ${actual:.2f} on {category} last month, "
                f"${overspend:.2f} more than the predicted ${predicted:.2f}. "
                f"Reducing {category} spending to the predicted level could save "
                f"~${overspend * 0.5:.2f}/month."
            )
            raw_suggestions.append(
                {
                    "suggestion_type": "reduce_category",
                    "category": category,
                    "description": desc,
                    "estimated_savings": round(overspend * 0.5, 2),
                }
            )

    # ── 3b. Recurring subscription detection ───────────────────────
    # Fetch all expenses over last 3 months; group by (description, amount)
    # in Python to stay SQLite-compatible.
    sub_result = await db.execute(
        select(
            Transaction.description,
            Transaction.amount,
            extract("year",  Transaction.date).label("yr"),
            extract("month", Transaction.date).label("mo"),
        )
        .where(
            and_(
                Transaction.user_id == user_id,
                Transaction.is_income == False,    # noqa: E712
                Transaction.is_duplicate == False, # noqa: E712
                Transaction.date >= three_months_ago,
            )
        )
        .distinct()
    )

    sub_rows = sub_result.all()

    # Count distinct (year, month) pairs per (description, amount)
    desc_amount_months: dict[tuple[str, str], set[tuple[int, int]]] = defaultdict(set)
    for r in sub_rows:
        key = (r.description, str(r.amount))
        desc_amount_months[key].add((int(r.yr), int(r.mo)))

    for (description, amount_str), months_set in desc_amount_months.items():
        if len(months_set) >= MIN_SUBSCRIPTION_MONTHS:
            monthly_cost = abs(float(amount_str))
            annual_cost = monthly_cost * 12
            desc_text = (
                f"Recurring charge detected: '{description}' for ${monthly_cost:.2f}/month. "
                f"If you no longer need this service, cancelling could save "
                f"~${annual_cost:.2f}/year."
            )
            raw_suggestions.append(
                {
                    "suggestion_type": "cancel_subscription",
                    "category": None,
                    "description": desc_text,
                    "estimated_savings": round(annual_cost, 2),
                }
            )

    # ── 3c. General tip when no specific suggestions generated ─────
    if not raw_suggestions and actual_by_cat:
        total_spend = sum(actual_by_cat.values())
        raw_suggestions.append(
            {
                "suggestion_type": "general",
                "category": None,
                "description": (
                    f"Your total expenses last month were ${total_spend:.2f}. "
                    "Consider reviewing your subscriptions and discretionary spending "
                    "to identify savings opportunities."
                ),
                "estimated_savings": None,
            }
        )

    # ── 4. Persist suggestions (replace stale non-dismissed ones) ──
    await db.execute(
        delete(SavingsSuggestion).where(
            and_(
                SavingsSuggestion.user_id == user_id,
                SavingsSuggestion.dismissed == False,  # noqa: E712
            )
        )
    )

    saved: list[dict] = []
    for s in raw_suggestions[:MAX_SUGGESTIONS]:
        estimated = (
            Decimal(str(s["estimated_savings"]))
            if s.get("estimated_savings") is not None
            else None
        )
        suggestion = SavingsSuggestion(
            user_id=user_id,
            suggestion_type=s["suggestion_type"],
            category=s.get("category"),
            description=s["description"],
            estimated_savings=estimated,
            dismissed=False,
        )
        db.add(suggestion)
        saved.append(s)

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    logger.info(
        "suggestions.generated",
        user_id=str(user_id),
        count=len(saved),
    )
    return saved

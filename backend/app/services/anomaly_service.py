"""
Anomaly detection service.

Three detectors:
1. Z-Score outlier - amount > 3 std-dev from mean in same category (last 90 days).
2. Category spike  - current-month total > 150% of 3-month rolling average.
3. Duplicate       - same (date, amount, description[:50]) already exists.
"""
import uuid
import statistics
from datetime import date, timedelta
from decimal import Decimal

import structlog
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction

logger = structlog.get_logger(__name__)


async def detect_zscore_anomalies(
    db: AsyncSession,
    user_id: uuid.UUID,
    statement_id: uuid.UUID,
    lookback_days: int = 90,
    threshold: float = 3.0,
) -> int:
    lookback = date.today() - timedelta(days=lookback_days)
    hist_result = await db.execute(
        select(Transaction.category, Transaction.amount)
        .where(and_(
            Transaction.user_id == user_id,
            Transaction.is_income == False,
            Transaction.date >= lookback,
            Transaction.statement_id != statement_id,
        ))
    )
    history: dict[str, list[float]] = {}
    for row in hist_result:
        cat = row.category or "Other"
        history.setdefault(cat, []).append(float(abs(row.amount)))

    cat_stats: dict[str, tuple[float, float]] = {}
    for cat, amounts in history.items():
        if len(amounts) >= 5:
            cat_stats[cat] = (statistics.mean(amounts), statistics.stdev(amounts))

    curr_result = await db.execute(
        select(Transaction).where(and_(
            Transaction.statement_id == statement_id,
            Transaction.is_income == False,
        ))
    )
    txns = list(curr_result.scalars())
    flagged = 0
    for txn in txns:
        cat = txn.category or "Other"
        if cat not in cat_stats:
            continue
        mean, stdev = cat_stats[cat]
        if stdev == 0:
            continue
        amount = float(abs(txn.amount))
        z = (amount - mean) / stdev
        if z > threshold:
            txn.is_anomaly = True
            score = Decimal(str(round(min(z / 10.0, 1.0), 4)))
            txn.anomaly_score = max(txn.anomaly_score or Decimal("0"), score)
            reason = f"Z-score={z:.2f}: unusually high {cat} (mean=${mean:.2f})"
            txn.anomaly_reason = (txn.anomaly_reason + " | " + reason) if txn.anomaly_reason else reason
            flagged += 1
    await db.flush()
    return flagged


async def detect_duplicates(
    db: AsyncSession,
    user_id: uuid.UUID,
    statement_id: uuid.UUID,
) -> int:
    curr_result = await db.execute(
        select(Transaction).where(Transaction.statement_id == statement_id)
    )
    txns = list(curr_result.scalars())
    flagged = 0
    for txn in txns:
        desc_prefix = txn.description[:50]
        existing_result = await db.execute(
            select(Transaction).where(and_(
                Transaction.user_id == user_id,
                Transaction.date == txn.date,
                Transaction.amount == txn.amount,
                Transaction.id != txn.id,
            )).limit(1)
        )
        existing = existing_result.scalar_one_or_none()
        if existing and existing.description[:50] == desc_prefix:
            txn.is_duplicate = True
            txn.duplicate_of = existing.id
            flagged += 1
    await db.flush()
    return flagged


async def detect_category_spikes(
    db: AsyncSession,
    user_id: uuid.UUID,
    statement_id: uuid.UUID,
    spike_factor: float = 1.5,
    lookback_months: int = 3,
) -> int:
    today = date.today()
    month_start = date(today.year, today.month, 1)
    curr_result = await db.execute(
        select(Transaction.category, func.sum(Transaction.amount).label("total"))
        .where(and_(
            Transaction.statement_id == statement_id,
            Transaction.is_income == False,
            Transaction.date >= month_start,
        ))
        .group_by(Transaction.category)
    )
    current_by_cat: dict[str, float] = {
        (r.category or "Other"): float(abs(r.total)) for r in curr_result
    }
    lookback_start = month_start
    for _ in range(lookback_months):
        lookback_start = (lookback_start - timedelta(days=1)).replace(day=1)
    hist_result = await db.execute(
        select(Transaction.category, func.sum(Transaction.amount).label("total"))
        .where(and_(
            Transaction.user_id == user_id,
            Transaction.is_income == False,
            Transaction.date >= lookback_start,
            Transaction.date < month_start,
        ))
        .group_by(Transaction.category)
    )
    historical_avg: dict[str, float] = {
        (r.category or "Other"): float(abs(r.total)) / lookback_months
        for r in hist_result
    }
    spiked_cats: set[str] = set()
    for cat, current_total in current_by_cat.items():
        avg = historical_avg.get(cat)
        if avg and avg > 0 and current_total > avg * spike_factor:
            spiked_cats.add(cat)
    if not spiked_cats:
        return 0
    txns_result = await db.execute(
        select(Transaction).where(and_(
            Transaction.statement_id == statement_id,
            Transaction.category.in_(spiked_cats),
        ))
    )
    txns = list(txns_result.scalars())
    for txn in txns:
        cat = txn.category or "Other"
        avg = historical_avg.get(cat, 0)
        ratio = current_by_cat[cat] / avg if avg > 0 else 0
        reason = f"Category spike: {cat} is {ratio:.1f}x the 3-month average"
        txn.is_anomaly = True
        txn.anomaly_score = txn.anomaly_score or Decimal("0.5")
        txn.anomaly_reason = (txn.anomaly_reason + " | " + reason) if txn.anomaly_reason else reason
    await db.flush()
    return len(txns)


async def run_all_detectors(
    db: AsyncSession,
    user_id: uuid.UUID,
    statement_id: uuid.UUID,
) -> dict:
    dup = await detect_duplicates(db, user_id, statement_id)
    zscore = await detect_zscore_anomalies(db, user_id, statement_id)
    spike = await detect_category_spikes(db, user_id, statement_id)
    logger.info("Anomaly detection complete", statement_id=str(statement_id),
                duplicates=dup, zscore_anomalies=zscore, category_spikes=spike)
    return {"duplicates": dup, "zscore_anomalies": zscore, "category_spikes": spike}

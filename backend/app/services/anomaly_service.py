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
from sqlalchemy import select, and_, func, tuple_
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
            Transaction.is_duplicate == False,  # exclude duplicates from baseline
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
            Transaction.is_duplicate == False,
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
            # Normalise z-score to 0-1 scale (capped at z=20 for max score)
            score = Decimal(str(round(min(z / 20.0, 1.0), 4)))
            txn.anomaly_score = max(txn.anomaly_score or Decimal("0"), score)
            reason = f"Unusually high {cat} spend (${amount:.2f} vs avg ${mean:.2f})"
            txn.anomaly_reason = (txn.anomaly_reason + " | " + reason) if txn.anomaly_reason else reason
            flagged += 1
    await db.flush()
    return flagged


async def detect_duplicates(
    db: AsyncSession,
    user_id: uuid.UUID,
    statement_id: uuid.UUID,
) -> int:
    """
    Batch duplicate detection — one query instead of N+1.
    Flags a transaction as duplicate if another transaction for the same user
    has an identical (date, amount, description[:50]) but a different id.
    """
    # Load all transactions for this statement
    curr_result = await db.execute(
        select(Transaction).where(Transaction.statement_id == statement_id)
    )
    txns = list(curr_result.scalars())
    if not txns:
        return 0

    # Build lookup keys (date, amount, desc_prefix)
    keys = [(t.date, t.amount, t.description[:50]) for t in txns]

    # Single query: find any existing transaction for this user that matches
    # any of those (date, amount, description-prefix) tuples
    # We use an OR of AND conditions (SQLAlchemy compiles efficiently)
    from sqlalchemy import or_
    conditions = [
        and_(
            Transaction.user_id == user_id,
            Transaction.date == k[0],
            Transaction.amount == k[1],
            Transaction.id.notin_([t.id for t in txns]),  # exclude self
        )
        for k in keys
    ]
    if not conditions:
        return 0

    existing_result = await db.execute(
        select(Transaction).where(or_(*conditions))
    )
    existing_txns = list(existing_result.scalars())

    # Build fast lookup: (date, amount, desc_prefix) → transaction
    existing_map: dict[tuple, Transaction] = {}
    for ex in existing_txns:
        key = (ex.date, ex.amount, ex.description[:50])
        existing_map[key] = ex

    flagged = 0
    for txn in txns:
        key = (txn.date, txn.amount, txn.description[:50])
        match = existing_map.get(key)
        if match:
            txn.is_duplicate = True
            txn.duplicate_of = match.id
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

    # Current month spending per category — exclude duplicates
    curr_result = await db.execute(
        select(Transaction.category, func.sum(Transaction.amount).label("total"))
        .where(and_(
            Transaction.statement_id == statement_id,
            Transaction.is_income == False,
            Transaction.is_duplicate == False,  # ← fixed: exclude duplicates
            Transaction.date >= month_start,
        ))
        .group_by(Transaction.category)
    )
    current_by_cat: dict[str, float] = {
        (r.category or "Other"): float(abs(r.total)) for r in curr_result
    }

    # Calculate lookback window start (go back exactly lookback_months months)
    lookback_start = month_start
    for _ in range(lookback_months):
        lookback_start = (lookback_start - timedelta(days=1)).replace(day=1)

    # Historical average per category — exclude duplicates
    hist_result = await db.execute(
        select(Transaction.category, func.sum(Transaction.amount).label("total"))
        .where(and_(
            Transaction.user_id == user_id,
            Transaction.is_income == False,
            Transaction.is_duplicate == False,  # ← fixed: exclude duplicates
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
            Transaction.is_duplicate == False,
            Transaction.category.in_(spiked_cats),
        ))
    )
    txns = list(txns_result.scalars())
    for txn in txns:
        cat = txn.category or "Other"
        avg = historical_avg.get(cat, 0)
        ratio = current_by_cat[cat] / avg if avg > 0 else 0
        reason = f"Category spike: {cat} is {ratio:.1f}x the {lookback_months}-month average"
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

"""
Statement service — business logic for file upload and processing pipeline.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import structlog
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.statement import BankStatement
from app.models.transaction import Transaction

logger = structlog.get_logger(__name__)


# ── Queries ───────────────────────────────────────────────────

async def get_statement(
    db: AsyncSession, statement_id: uuid.UUID, user_id: uuid.UUID
) -> BankStatement | None:
    result = await db.execute(
        select(BankStatement).where(
            BankStatement.id == statement_id,
            BankStatement.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def list_statements(
    db: AsyncSession,
    user_id: uuid.UUID,
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[BankStatement], int]:
    count_result = await db.execute(
        select(func.count()).select_from(BankStatement).where(BankStatement.user_id == user_id)
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.user_id == user_id)
        .order_by(BankStatement.uploaded_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars()), total


# ── Worker-facing helpers ─────────────────────────────────────

async def mark_processing(db: AsyncSession, statement_id: uuid.UUID) -> BankStatement | None:
    result = await db.execute(
        select(BankStatement).where(BankStatement.id == statement_id)
    )
    stmt = result.scalar_one_or_none()
    if stmt:
        stmt.status = "processing"
        await db.flush()
    return stmt


async def mark_completed(
    db: AsyncSession,
    statement_id: uuid.UUID,
    row_count: int,
) -> None:
    result = await db.execute(
        select(BankStatement).where(BankStatement.id == statement_id)
    )
    stmt = result.scalar_one_or_none()
    if stmt:
        stmt.status = "completed"
        stmt.row_count = row_count
        stmt.processed_at = datetime.now(timezone.utc)
        await db.flush()
    logger.info("Statement marked completed", statement_id=str(statement_id), rows=row_count)


async def mark_failed(
    db: AsyncSession,
    statement_id: uuid.UUID,
    error_message: str,
) -> None:
    result = await db.execute(
        select(BankStatement).where(BankStatement.id == statement_id)
    )
    stmt = result.scalar_one_or_none()
    if stmt:
        stmt.status = "failed"
        stmt.error_message = error_message[:1000]  # truncate to DB column size
        stmt.processed_at = datetime.now(timezone.utc)
        await db.flush()
    logger.error("Statement marked failed", statement_id=str(statement_id), error=error_message)


async def bulk_insert_transactions(
    db: AsyncSession,
    user_id: uuid.UUID,
    statement_id: uuid.UUID,
    parsed_rows: list,  # list[ParsedTransaction]
) -> int:
    """
    Insert parsed transactions into the DB.
    Returns the number of rows inserted.
    """
    rows = [
        Transaction(
            user_id=user_id,
            statement_id=statement_id,
            date=row.date,
            description=row.description,
            amount=row.amount,
            is_income=row.amount > Decimal("0"),
        )
        for row in parsed_rows
    ]
    db.add_all(rows)
    await db.flush()
    logger.info(
        "Transactions inserted",
        statement_id=str(statement_id),
        count=len(rows),
    )
    return len(rows)

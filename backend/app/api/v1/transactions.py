"""
Transactions router — list, filter, update category, export.
"""
import uuid
from datetime import date

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.transaction import (
    TransactionResponse,
    UpdateCategoryRequest,
)

router = APIRouter()
logger = structlog.get_logger(__name__)


# ── GET /transactions ─────────────────────────────────────────

@router.get("", summary="List transactions with optional filters")
async def list_transactions(
    statement_id: uuid.UUID | None = Query(default=None),
    category: str | None = Query(default=None),
    is_income: bool | None = Query(default=None),
    is_anomaly: bool | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    search: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    filters = [Transaction.user_id == current_user.id]
    actual_skip = offset or skip  # accept both names

    if statement_id is not None:
        filters.append(Transaction.statement_id == statement_id)
    if category is not None:
        filters.append(Transaction.category == category)
    if is_income is not None:
        filters.append(Transaction.is_income == is_income)
    if is_anomaly is not None:
        filters.append(Transaction.is_anomaly == is_anomaly)
    if date_from is not None:
        filters.append(Transaction.date >= date_from)
    if date_to is not None:
        filters.append(Transaction.date <= date_to)
    if search is not None:
        filters.append(Transaction.description.ilike(f"%{search}%"))

    where = and_(*filters)

    count_result = await db.execute(
        select(func.count()).select_from(Transaction).where(where)
    )
    total = count_result.scalar_one()
    pages = max(1, (total + limit - 1) // limit)
    page = actual_skip // limit + 1

    result = await db.execute(
        select(Transaction)
        .where(where)
        .order_by(Transaction.date.desc(), Transaction.created_at.desc())
        .offset(actual_skip)
        .limit(limit)
    )
    txns = list(result.scalars())

    return {
        "items": [TransactionResponse.model_validate(t) for t in txns],
        "total": total,
        "page": page,
        "pages": pages,
    }


# ── GET /transactions/{id} ────────────────────────────────────

@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TransactionResponse:
    result = await db.execute(
        select(Transaction).where(
            Transaction.id == transaction_id,
            Transaction.user_id == current_user.id,
        )
    )
    txn = result.scalar_one_or_none()
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return TransactionResponse.model_validate(txn)


# ── PATCH /transactions/{id}/category ────────────────────────

@router.patch(
    "/{transaction_id}/category",
    response_model=TransactionResponse,
    summary="Override the AI-assigned category",
)
async def update_transaction_category(
    transaction_id: uuid.UUID,
    body: UpdateCategoryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TransactionResponse:
    result = await db.execute(
        select(Transaction).where(
            Transaction.id == transaction_id,
            Transaction.user_id == current_user.id,
        )
    )
    txn = result.scalar_one_or_none()
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    txn.user_category = body.category
    txn.category = body.category          # also update displayed category
    txn.categorization_source = "user"
    await db.flush()

    logger.info(
        "Transaction category updated",
        transaction_id=str(transaction_id),
        category=body.category,
    )
    return TransactionResponse.model_validate(txn)

"""
Statements router — file upload and management.

Upload flow:
  1. Client POST /upload with {file_name, file_type}
  2. Backend creates DB record (status=pending), publishes to SQS
  3. Backend returns pre-signed S3 URL
  4. Client uploads file directly to S3 (not through the backend)
  5. SQS worker processes the file asynchronously
"""
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.sqs.producer import sqs_producer
from app.sqs.queues import Queues
from app.models.statement import BankStatement
from app.models.user import User
from app.schemas.statement import (
    StatementListResponse,
    StatementResponse,
    StatementUploadRequest,
    StatementUploadResponse,
)
from app.services.statement_service import get_statement, list_statements
from app.utils.s3 import delete_object, generate_presigned_upload_url

router = APIRouter()
logger = structlog.get_logger(__name__)

_CONTENT_TYPES = {"csv": "text/csv", "pdf": "application/pdf"}


# ── POST /upload ──────────────────────────────────────────────

@router.post(
    "/upload",
    response_model=StatementUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request a pre-signed S3 URL for direct file upload",
)
async def upload_statement(
    body: StatementUploadRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StatementUploadResponse:
    """
    Creates a BankStatement record in 'pending' state and returns a
    pre-signed S3 POST URL. The client uploads directly to S3 using
    that URL + the returned `upload_fields`.
    """
    s3_key = f"statements/{current_user.id}/{uuid.uuid4()}.{body.file_type}"

    # Persist DB record first
    statement = BankStatement(
        user_id=current_user.id,
        file_name=body.file_name,
        s3_key=s3_key,
        file_type=body.file_type,
        status="pending",
    )
    db.add(statement)
    await db.flush()

    # Generate pre-signed upload URL
    try:
        presigned = await generate_presigned_upload_url(
            key=s3_key,
            content_type=_CONTENT_TYPES[body.file_type],
        )
    except Exception as exc:
        logger.error("S3 pre-signed URL generation failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage service unavailable. Please try again later.",
        )

    # Publish to SQS so the parser worker picks it up after the client uploads
    try:
        await sqs_producer.send(
            queue_url=Queues.statement_uploaded(),
            payload={
                "statement_id": str(statement.id),
                "user_id": str(current_user.id),
                "s3_key": s3_key,
                "file_type": body.file_type,
            },
        )
    except Exception as exc:
        # Non-fatal: user can manually trigger reprocess later
        logger.warning(
            "Failed to publish to SQS — statement queued for manual reprocess",
            statement_id=str(statement.id),
            error=str(exc),
        )

    logger.info(
        "Statement upload initiated",
        statement_id=str(statement.id),
        user_id=str(current_user.id),
        file_type=body.file_type,
    )

    return StatementUploadResponse(
        statement_id=statement.id,
        upload_url=presigned["url"],
        upload_fields=presigned["fields"],
        s3_key=s3_key,
    )


# ── GET / ─────────────────────────────────────────────────────

@router.get(
    "",
    response_model=StatementListResponse,
    summary="List all statements for the current user",
)
async def list_user_statements(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StatementListResponse:
    statements, total = await list_statements(db, current_user.id, skip=skip, limit=limit)
    return StatementListResponse(
        statements=[StatementResponse.model_validate(s) for s in statements],
        total=total,
    )


# ── GET /{id} ─────────────────────────────────────────────────

@router.get(
    "/{statement_id}",
    response_model=StatementResponse,
    summary="Get a single statement by ID",
)
async def get_user_statement(
    statement_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StatementResponse:
    stmt = await get_statement(db, statement_id, current_user.id)
    if stmt is None:
        raise HTTPException(status_code=404, detail="Statement not found")
    return StatementResponse.model_validate(stmt)


# ── DELETE /{id} ──────────────────────────────────────────────

@router.delete(
    "/{statement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a statement and its transactions",
)
async def delete_statement(
    statement_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    stmt = await get_statement(db, statement_id, current_user.id)
    if stmt is None:
        raise HTTPException(status_code=404, detail="Statement not found")

    # Delete from S3 (best-effort)
    await delete_object(stmt.s3_key)

    # Cascade deletes transactions via FK constraint
    await db.delete(stmt)
    await db.flush()

    logger.info("Statement deleted", statement_id=str(statement_id))


# ── POST /{id}/reprocess ──────────────────────────────────────

@router.post(
    "/{statement_id}/reprocess",
    response_model=StatementResponse,
    summary="Re-trigger parsing for a failed or stuck statement",
)
async def reprocess_statement(
    statement_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StatementResponse:
    stmt = await get_statement(db, statement_id, current_user.id)
    if stmt is None:
        raise HTTPException(status_code=404, detail="Statement not found")

    if stmt.status == "processing":
        raise HTTPException(status_code=409, detail="Statement is already being processed")

    # Reset status
    stmt.status = "pending"
    stmt.error_message = None
    await db.flush()

    try:
        await sqs_producer.send(
            queue_url=Queues.statement_uploaded(),
            payload={
                "statement_id": str(stmt.id),
                "user_id": str(current_user.id),
                "s3_key": stmt.s3_key,
                "file_type": stmt.file_type,
            },
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Could not queue statement for reprocessing. Try again later.",
        )

    logger.info("Statement reprocess triggered", statement_id=str(statement_id))
    return StatementResponse.model_validate(stmt)

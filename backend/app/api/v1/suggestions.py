"""
Suggestions router — Premium feature.

Endpoints:
  GET   /suggestions/           — list active suggestions (premium)
  POST  /suggestions/{id}/dismiss — dismiss a suggestion (premium)
  POST  /suggestions/generate   — generate fresh suggestions (premium)
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_premium
from app.database import get_db
from app.models.suggestion import SavingsSuggestion
from app.models.user import User
from app.schemas.suggestion import (
    GenerateSuggestionsResponse,
    SuggestionResponse,
    SuggestionsListResponse,
)
from app.services.suggestion_service import generate_suggestions_for_user

router = APIRouter()


# ── GET /suggestions/ ─────────────────────────────────────────

@router.get("/", response_model=SuggestionsListResponse)
async def list_suggestions(
    include_dismissed: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_premium),
) -> SuggestionsListResponse:
    """List all savings suggestions for the current user (premium only)."""
    stmt = select(SavingsSuggestion).where(
        SavingsSuggestion.user_id == current_user.id
    )
    if not include_dismissed:
        stmt = stmt.where(SavingsSuggestion.dismissed == False)   # noqa: E712
    stmt = stmt.order_by(SavingsSuggestion.generated_at.desc())

    result = await db.execute(stmt)
    suggestions = list(result.scalars().all())

    return SuggestionsListResponse(
        suggestions=[SuggestionResponse.model_validate(s) for s in suggestions],
        total=len(suggestions),
    )


# ── POST /suggestions/{id}/dismiss ────────────────────────────

@router.post("/{suggestion_id}/dismiss", response_model=SuggestionResponse)
async def dismiss_suggestion(
    suggestion_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_premium),
) -> SuggestionResponse:
    """Mark a suggestion as dismissed (premium only)."""
    result = await db.execute(
        select(SavingsSuggestion).where(
            and_(
                SavingsSuggestion.id == suggestion_id,
                SavingsSuggestion.user_id == current_user.id,
            )
        )
    )
    suggestion = result.scalar_one_or_none()

    if suggestion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Suggestion not found",
        )

    suggestion.dismissed = True
    await db.commit()
    await db.refresh(suggestion)
    return SuggestionResponse.model_validate(suggestion)


# ── POST /suggestions/generate ────────────────────────────────

@router.post("/generate", response_model=GenerateSuggestionsResponse)
async def generate_suggestions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_premium),
) -> GenerateSuggestionsResponse:
    """Trigger on-demand suggestion generation (premium only)."""
    generated = await generate_suggestions_for_user(db, current_user.id)
    return GenerateSuggestionsResponse(
        generated=len(generated),
        message=f"Generated {len(generated)} savings suggestions.",
    )

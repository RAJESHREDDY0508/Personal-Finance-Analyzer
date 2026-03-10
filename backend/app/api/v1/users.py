"""
Users router — current user profile management.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.auth import MessageResponse
from app.schemas.user import UpdateUserRequest, UserResponse

router = APIRouter()


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile",
)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """Return the authenticated user's profile."""
    return UserResponse.model_validate(current_user)


@router.patch(
    "/me",
    response_model=UserResponse,
    summary="Update current user profile",
)
async def update_me(
    body: UpdateUserRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Update mutable profile fields (full_name, email_reports)."""
    if body.full_name is not None:
        current_user.full_name = body.full_name
    if body.email_reports is not None:
        current_user.email_reports = body.email_reports

    db.add(current_user)
    return UserResponse.model_validate(current_user)


@router.delete(
    "/me",
    response_model=MessageResponse,
    summary="Deactivate current user account",
)
async def delete_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """
    Soft-delete: marks the account inactive.
    The user's data is retained; they can contact support to restore.
    """
    current_user.is_active = False
    db.add(current_user)
    return MessageResponse(message="Account deactivated successfully.")

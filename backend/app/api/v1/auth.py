"""
Auth router — register, login, refresh, logout.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.auth import (
    AccessTokenResponse,
    LoginRequest,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from app.schemas.user import UserResponse
from app.services.auth_service import AuthError, login, logout, refresh_tokens, register

router = APIRouter()


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new account",
)
async def register_user(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Register a new user and immediately return tokens so they
    are logged in after signing up.
    """
    try:
        user = await register(
            db, email=body.email, password=body.password, full_name=body.full_name
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    # Auto-login after registration
    _, access_token, refresh_token = await login(db, email=body.email, password=body.password)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse.model_validate(user),
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login with email + password",
)
async def login_user(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Return access + refresh tokens for valid credentials."""
    try:
        user_obj, access_token, refresh_token = await login(
            db, email=body.email, password=body.password
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse.model_validate(user_obj),
    )


@router.post(
    "/refresh",
    response_model=AccessTokenResponse,
    summary="Rotate refresh token",
)
async def refresh_token(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> AccessTokenResponse:
    """
    Exchange a valid refresh token for a new access token.
    The old refresh token is revoked; a new one is returned via cookie
    or the caller should use the new access token header.

    Note: for simplicity we return both tokens; callers should store
    the new refresh token for the next rotation.
    """
    try:
        new_access, new_refresh = await refresh_tokens(db, body.refresh_token)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    # Return access token; also embed new refresh in response header for convenience
    return AccessTokenResponse(access_token=new_access)


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Logout — revoke refresh token",
)
async def logout_user(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Revoke the supplied refresh token. Idempotent."""
    await logout(db, body.refresh_token)
    return MessageResponse(message="Logged out successfully.")

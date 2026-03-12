"""
Google OAuth 2.0 authentication flow.

GET /auth/google/authorize  → redirect to Google consent screen
GET /auth/google/callback   → exchange code, find/create user, redirect to frontend
"""
from __future__ import annotations

import hashlib
import secrets
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import RefreshToken, User
from app.utils.security import create_access_token, create_refresh_token

logger = structlog.get_logger(__name__)
router = APIRouter()

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

_SCOPES = "openid email profile"


@router.get("/authorize", summary="Redirect to Google OAuth consent screen")
async def google_authorize() -> RedirectResponse:
    """Build Google authorization URL and redirect."""
    if not settings.google_client_id:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": _SCOPES,
        "access_type": "offline",
        "prompt": "select_account",
    }
    url = f"{_GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"
    return RedirectResponse(url=url)


@router.get("/callback", summary="Google OAuth callback — exchange code for tokens")
async def google_callback(
    code: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Exchange authorization code for Google tokens, find or create user, return JWT."""
    frontend_base = settings.frontend_url

    if error or not code:
        return RedirectResponse(
            url=f"{frontend_base}/login?error=google_auth_failed"
        )

    # ── Exchange code for Google tokens ──────────────────────────
    async with httpx.AsyncClient() as client:
        try:
            token_resp = await client.post(
                _GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": settings.google_redirect_uri,
                    "grant_type": "authorization_code",
                },
                timeout=15.0,
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()

            userinfo_resp = await client.get(
                _GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {token_data['access_token']}"},
                timeout=10.0,
            )
            userinfo_resp.raise_for_status()
            userinfo = userinfo_resp.json()

        except Exception as exc:
            logger.error("Google OAuth token exchange failed", error=str(exc))
            return RedirectResponse(
                url=f"{frontend_base}/login?error=google_token_failed"
            )

    google_id: str = userinfo.get("sub", "")
    email: str = userinfo.get("email", "")
    name: str | None = userinfo.get("name")
    avatar_url: str | None = userinfo.get("picture")

    if not email or not google_id:
        return RedirectResponse(url=f"{frontend_base}/login?error=google_missing_info")

    # ── Find or create user ───────────────────────────────────────
    result = await db.execute(select(User).where(User.google_id == google_id))
    user = result.scalar_one_or_none()

    if user is None:
        # Try to find by email (link existing account)
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

    if user is None:
        # Create new Google user
        user = User(
            id=uuid.uuid4(),
            email=email,
            password_hash=secrets.token_hex(32),  # random, not usable for login
            full_name=name,
            google_id=google_id,
            avatar_url=avatar_url,
            plan="free",
        )
        db.add(user)
    else:
        # Update profile data from Google
        if not user.google_id:
            user.google_id = google_id
        if avatar_url and not user.avatar_url:
            user.avatar_url = avatar_url
        if name and not user.full_name:
            user.full_name = name

    # ── Issue our own JWT tokens ──────────────────────────────────
    user_id_str = str(user.id)
    access_token = create_access_token(user_id_str)
    raw_refresh = create_refresh_token(user_id_str)

    # Store hashed refresh token (same pattern as auth_service)
    refresh_hash = hashlib.sha256(raw_refresh.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.jwt_refresh_token_expire_days
    )
    rt = RefreshToken(
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=expires_at,
    )
    db.add(rt)
    await db.commit()

    # ── Redirect to frontend OAuth callback with tokens ───────────
    params = urllib.parse.urlencode({
        "access_token": access_token,
        "refresh_token": raw_refresh,
    })
    return RedirectResponse(url=f"{frontend_base}/oauth-callback?{params}")

"""
Auth service — register, login, refresh, logout.
All database operations; no HTTP concerns.
"""
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import RefreshToken, User
from app.utils.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)

logger = structlog.get_logger(__name__)


# ── Helpers ───────────────────────────────────────────────────

def _hash_token(raw_token: str) -> str:
    """SHA-256 hash of the raw refresh token for safe DB storage."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


async def _get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def _store_refresh_token(
    db: AsyncSession, user_id: uuid.UUID, raw_token: str
) -> None:
    """Persist a hashed refresh token to the DB."""
    token_hash = _hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.jwt_refresh_token_expire_days
    )
    db_token = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(db_token)
    await db.flush()


async def _revoke_refresh_token(db: AsyncSession, raw_token: str) -> bool:
    """
    Mark a refresh token as revoked.
    Returns True if found and revoked, False if not found.
    """
    token_hash = _hash_token(raw_token)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked == False,  # noqa: E712
        )
    )
    db_token = result.scalar_one_or_none()
    if db_token is None:
        return False
    db_token.revoked = True
    await db.flush()
    return True


# ── Public API ────────────────────────────────────────────────

class AuthError(Exception):
    """Raised for domain-level auth failures (duplicate email, bad password, etc.)"""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


async def register(
    db: AsyncSession,
    email: str,
    password: str,
    full_name: str | None = None,
) -> User:
    """
    Create a new user account.
    Raises AuthError if the email is already taken.
    """
    existing = await _get_user_by_email(db, email.lower())
    if existing is not None:
        raise AuthError("An account with this email already exists.", status_code=409)

    user = User(
        email=email.lower(),
        password_hash=hash_password(password),
        full_name=full_name,
    )
    db.add(user)
    await db.flush()

    logger.info("User registered", user_id=str(user.id), email=user.email)
    return user


async def login(
    db: AsyncSession,
    email: str,
    password: str,
) -> tuple[User, str, str]:
    """
    Authenticate a user.
    Returns (user, access_token, refresh_token).
    Raises AuthError on bad credentials.
    """
    user = await _get_user_by_email(db, email.lower())

    if user is None or not verify_password(password, user.password_hash):
        raise AuthError("Invalid email or password.", status_code=401)

    if not user.is_active:
        raise AuthError("Account is deactivated.", status_code=403)

    access_token = create_access_token(str(user.id))
    refresh_token = create_refresh_token(str(user.id))
    await _store_refresh_token(db, user.id, refresh_token)

    logger.info("User logged in", user_id=str(user.id))
    return user, access_token, refresh_token


async def refresh_tokens(
    db: AsyncSession,
    raw_refresh_token: str,
) -> tuple[str, str]:
    """
    Rotate refresh token — revoke old, issue new pair.
    Returns (new_access_token, new_refresh_token).
    Raises AuthError if token is invalid or already revoked.
    """
    payload = decode_refresh_token(raw_refresh_token)
    if payload is None:
        raise AuthError("Invalid or expired refresh token.", status_code=401)

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise AuthError("Malformed token.", status_code=401)

    # Verify token exists in DB and is not revoked
    token_hash = _hash_token(raw_refresh_token)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked == False,  # noqa: E712
        )
    )
    db_token = result.scalar_one_or_none()

    if db_token is None:
        raise AuthError("Refresh token not found or already revoked.", status_code=401)

    if db_token.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        db_token.revoked = True
        raise AuthError("Refresh token expired.", status_code=401)

    # Revoke old, issue new pair
    db_token.revoked = True
    await db.flush()

    user_id = uuid.UUID(user_id_str)
    new_access = create_access_token(str(user_id))
    new_refresh = create_refresh_token(str(user_id))
    await _store_refresh_token(db, user_id, new_refresh)

    logger.info("Tokens refreshed", user_id=user_id_str)
    return new_access, new_refresh


async def logout(db: AsyncSession, raw_refresh_token: str) -> None:
    """
    Invalidate a refresh token. Silent if already gone — idempotent.
    """
    revoked = await _revoke_refresh_token(db, raw_refresh_token)
    if revoked:
        logger.info("User logged out")

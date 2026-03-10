"""
Security utilities — password hashing and JWT encode/decode.
Uses argon2-cffi for password hashing (bcrypt has Python 3.14 compat issues).
Each JWT carries a unique `jti` (JWT ID) to prevent same-second hash collisions
when tokens are issued/rotated within the same clock tick.
"""
import uuid
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from jose import JWTError, jwt

from app.config import settings

# ── Password hashing ──────────────────────────────────────────
_ph = PasswordHasher()


def hash_password(plain: str) -> str:
    """Return Argon2 hash of the plain-text password."""
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if plain matches the hashed password."""
    try:
        return _ph.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# ── JWT ───────────────────────────────────────────────────────
def create_access_token(user_id: str) -> str:
    """Create a short-lived JWT access token (unique jti per call)."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_access_token_expire_minutes
    )
    payload = {
        "sub": user_id,
        "type": "access",
        "exp": expire,
        "jti": str(uuid.uuid4()),   # Unique per token; prevents same-second collisions
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: str) -> str:
    """Create a long-lived JWT refresh token (unique jti per call)."""
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.jwt_refresh_token_expire_days
    )
    payload = {
        "sub": user_id,
        "type": "refresh",
        "exp": expire,
        "jti": str(uuid.uuid4()),   # Unique per token; prevents rotation hash collisions
    }
    return jwt.encode(
        payload, settings.jwt_refresh_secret_key, algorithm=settings.jwt_algorithm
    )


def decode_access_token(token: str) -> dict | None:
    """
    Decode and validate a JWT access token.
    Returns the payload dict, or None if invalid/expired.
    """
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        if payload.get("type") != "access":
            return None
        return payload
    except JWTError:
        return None


def decode_refresh_token(token: str) -> dict | None:
    """
    Decode and validate a JWT refresh token.
    Returns the payload dict, or None if invalid/expired.
    """
    try:
        payload = jwt.decode(
            token, settings.jwt_refresh_secret_key, algorithms=[settings.jwt_algorithm]
        )
        if payload.get("type") != "refresh":
            return None
        return payload
    except JWTError:
        return None

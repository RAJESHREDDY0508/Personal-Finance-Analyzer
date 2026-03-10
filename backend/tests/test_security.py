"""
Unit tests for security utilities — password hashing and JWT.
These tests do NOT require a DB connection.
"""
import time
import pytest

from app.utils.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)


# ─────────────────────────────────────────────────────────────
# Password hashing
# ─────────────────────────────────────────────────────────────

def test_hash_password_returns_string() -> None:
    result = hash_password("mysecretpassword")
    assert isinstance(result, str)
    assert len(result) > 20


def test_hash_password_is_not_plaintext() -> None:
    plain = "mysecretpassword"
    hashed = hash_password(plain)
    assert plain not in hashed


def test_hash_password_different_each_call() -> None:
    """bcrypt includes a random salt — two hashes of same password differ."""
    h1 = hash_password("samepassword")
    h2 = hash_password("samepassword")
    assert h1 != h2


def test_verify_password_correct() -> None:
    plain = "correctpassword"
    hashed = hash_password(plain)
    assert verify_password(plain, hashed) is True


def test_verify_password_wrong() -> None:
    hashed = hash_password("correctpassword")
    assert verify_password("wrongpassword", hashed) is False


def test_verify_password_empty_vs_hash() -> None:
    hashed = hash_password("nonempty")
    assert verify_password("", hashed) is False


# ─────────────────────────────────────────────────────────────
# JWT access tokens
# ─────────────────────────────────────────────────────────────

def test_create_access_token_returns_string() -> None:
    token = create_access_token("user-123")
    assert isinstance(token, str)
    assert len(token.split(".")) == 3  # header.payload.signature


def test_decode_access_token_valid() -> None:
    user_id = "user-abc-123"
    token = create_access_token(user_id)
    payload = decode_access_token(token)

    assert payload is not None
    assert payload["sub"] == user_id
    assert payload["type"] == "access"


def test_decode_access_token_wrong_secret() -> None:
    """A token signed with a different key must not decode."""
    from jose import jwt
    import app.config as cfg

    fake_token = jwt.encode(
        {"sub": "x", "type": "access"},
        "wrong-secret",
        algorithm=cfg.settings.jwt_algorithm,
    )
    assert decode_access_token(fake_token) is None


def test_decode_access_token_wrong_type() -> None:
    """A refresh token must not be accepted as an access token."""
    refresh = create_refresh_token("user-123")
    assert decode_access_token(refresh) is None


def test_decode_access_token_invalid_string() -> None:
    assert decode_access_token("not.a.token") is None


def test_decode_access_token_empty() -> None:
    assert decode_access_token("") is None


# ─────────────────────────────────────────────────────────────
# JWT refresh tokens
# ─────────────────────────────────────────────────────────────

def test_create_refresh_token_returns_string() -> None:
    token = create_refresh_token("user-456")
    assert isinstance(token, str)


def test_decode_refresh_token_valid() -> None:
    user_id = "user-456"
    token = create_refresh_token(user_id)
    payload = decode_refresh_token(token)

    assert payload is not None
    assert payload["sub"] == user_id
    assert payload["type"] == "refresh"


def test_decode_refresh_token_wrong_type() -> None:
    """An access token must not be accepted as a refresh token."""
    access = create_access_token("user-123")
    assert decode_refresh_token(access) is None


def test_access_and_refresh_tokens_are_different() -> None:
    user_id = "user-789"
    access = create_access_token(user_id)
    refresh = create_refresh_token(user_id)
    assert access != refresh

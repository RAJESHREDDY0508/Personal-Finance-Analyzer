"""
Phase 1 — Auth tests.
Covers: register, login, refresh, logout, /me endpoints.
Uses in-memory SQLite via conftest fixtures.
"""
import pytest
from httpx import AsyncClient


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

REGISTER_PAYLOAD = {
    "email": "alice@example.com",
    "password": "SecurePass123",
    "full_name": "Alice Test",
}

LOGIN_PAYLOAD = {
    "email": "alice@example.com",
    "password": "SecurePass123",
}


async def _register_and_login(client: AsyncClient) -> dict:
    """Register a user and return the token response JSON."""
    resp = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert resp.status_code == 201
    return resp.json()


# ─────────────────────────────────────────────────────────────
# Register
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_success(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    resp = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_register_short_password(client: AsyncClient) -> None:
    payload = {**REGISTER_PAYLOAD, "email": "bob@example.com", "password": "short"}
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 422  # Pydantic validation


@pytest.mark.asyncio
async def test_register_invalid_email(client: AsyncClient) -> None:
    payload = {**REGISTER_PAYLOAD, "email": "not-an-email"}
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────
# Login
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_success(client: AsyncClient) -> None:
    await _register_and_login(client)
    resp = await client.post("/api/v1/auth/login", json=LOGIN_PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient) -> None:
    await _register_and_login(client)
    resp = await client.post(
        "/api/v1/auth/login",
        json={**LOGIN_PAYLOAD, "password": "WrongPassword!"},
    )
    assert resp.status_code == 401
    assert "Invalid" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_login_unknown_email(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "SecurePass123"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_email_case_insensitive(client: AsyncClient) -> None:
    await _register_and_login(client)
    resp = await client.post(
        "/api/v1/auth/login",
        json={**LOGIN_PAYLOAD, "email": "ALICE@EXAMPLE.COM"},
    )
    assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────
# Token refresh
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refresh_success(client: AsyncClient) -> None:
    tokens = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_refresh_invalid_token(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "this.is.not.valid"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_reuse_revoked_token(client: AsyncClient) -> None:
    """Reusing a refresh token after rotation should fail (token rotation security)."""
    tokens = await _register_and_login(client)
    old_refresh = tokens["refresh_token"]

    # First refresh — rotates the token
    resp1 = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": old_refresh},
    )
    assert resp1.status_code == 200

    # Second use of the same old token — should be rejected
    resp2 = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": old_refresh},
    )
    assert resp2.status_code == 401


# ─────────────────────────────────────────────────────────────
# Logout
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_logout_success(client: AsyncClient) -> None:
    tokens = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert resp.status_code == 200
    assert "Logged out" in resp.json()["message"]


@pytest.mark.asyncio
async def test_logout_idempotent(client: AsyncClient) -> None:
    """Logging out twice should not raise an error."""
    tokens = await _register_and_login(client)
    payload = {"refresh_token": tokens["refresh_token"]}

    await client.post("/api/v1/auth/logout", json=payload)
    resp = await client.post("/api/v1/auth/logout", json=payload)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_refresh_after_logout_fails(client: AsyncClient) -> None:
    """After logout, the refresh token must be invalid."""
    tokens = await _register_and_login(client)
    refresh = tokens["refresh_token"]

    await client.post("/api/v1/auth/logout", json={"refresh_token": refresh})

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 401


# ─────────────────────────────────────────────────────────────
# /me endpoints
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_me(client: AsyncClient) -> None:
    tokens = await _register_and_login(client)
    resp = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "alice@example.com"
    assert data["full_name"] == "Alice Test"
    assert data["plan"] == "free"


@pytest.mark.asyncio
async def test_get_me_no_token(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users/me")
    assert resp.status_code == 401  # HTTPBearer returns 401 when no Authorization header


@pytest.mark.asyncio
async def test_get_me_invalid_token(client: AsyncClient) -> None:
    resp = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer invalid.token.here"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_update_me_full_name(client: AsyncClient) -> None:
    tokens = await _register_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    resp = await client.patch(
        "/api/v1/users/me",
        json={"full_name": "Alice Updated"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Alice Updated"


@pytest.mark.asyncio
async def test_update_me_email_reports(client: AsyncClient) -> None:
    tokens = await _register_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    resp = await client.patch(
        "/api/v1/users/me",
        json={"email_reports": False},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["email_reports"] is False


@pytest.mark.asyncio
async def test_delete_me(client: AsyncClient) -> None:
    tokens = await _register_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    resp = await client.delete("/api/v1/users/me", headers=headers)
    assert resp.status_code == 200
    assert "deactivated" in resp.json()["message"]

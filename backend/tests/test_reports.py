"""
Tests for monthly report generation, email service, and report API endpoints.

AWS S3 and SES calls are mocked with unittest.mock so no real credentials needed.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction
from app.models.report import MonthlyReport
from app.services.report_service import (
    generate_monthly_report,
    get_user_reports,
    get_report_download_url,
    mark_email_sent,
)
from app.services.email_service import send_monthly_report_email


# ── Helpers ───────────────────────────────────────────────────

REGISTER_PAYLOAD = {"email": "report_user@example.com", "password": "TestPass123"}


async def _auth_headers(client: AsyncClient) -> dict:
    resp = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert resp.status_code in (200, 201)
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _get_user_id(headers: dict) -> uuid.UUID:
    from app.utils.security import decode_access_token
    token = headers["Authorization"].split(" ")[1]
    return uuid.UUID(decode_access_token(token)["sub"])


async def _seed_transactions(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Insert a minimal set of transactions for the current month."""
    stmt_id = uuid.uuid4()
    today = date.today()
    rows = [
        Transaction(
            user_id=user_id, statement_id=stmt_id, date=today,
            description="SALARY", amount=Decimal("4000"), is_income=True, category="Income",
        ),
        Transaction(
            user_id=user_id, statement_id=stmt_id, date=today,
            description="RENT", amount=Decimal("-1500"), is_income=False, category="Housing",
        ),
        Transaction(
            user_id=user_id, statement_id=stmt_id, date=today,
            description="GROCERIES", amount=Decimal("-300"), is_income=False, category="Food",
        ),
        Transaction(
            user_id=user_id, statement_id=stmt_id, date=today,
            description="GAS", amount=Decimal("-80"), is_income=False, category="Transport",
        ),
    ]
    db.add_all(rows)
    await db.commit()


# ── report_service tests ───────────────────────────────────────

@pytest.mark.anyio
async def test_generate_monthly_report_creates_record(db_session: AsyncSession, client: AsyncClient):
    """generate_monthly_report should create a MonthlyReport row with correct data."""
    headers = await _auth_headers(client)
    user_id = await _get_user_id(headers)
    await _seed_transactions(db_session, user_id)

    today = date.today()

    # Mock S3 so upload doesn't need real AWS
    with patch("app.services.report_service._get_s3_client") as mock_s3:
        mock_client = MagicMock()
        mock_client.put_object.return_value = {}
        mock_s3.return_value = mock_client

        report = await generate_monthly_report(
            db=db_session,
            user_id=user_id,
            year=today.year,
            month=today.month,
            user_name="Test User",
        )

    assert report.user_id == user_id
    assert report.report_month == date(today.year, today.month, 1)
    assert report.total_income == Decimal("4000")
    assert report.total_expenses == Decimal("1880")      # 1500 + 300 + 80
    assert report.health_score is not None
    assert report.health_score >= 0
    assert report.health_score <= 100
    assert report.s3_key is not None


@pytest.mark.anyio
async def test_generate_monthly_report_upserts(db_session: AsyncSession, client: AsyncClient):
    """Calling generate_monthly_report twice for the same month should upsert, not duplicate."""
    headers = await _auth_headers(client)
    user_id = await _get_user_id(headers)
    await _seed_transactions(db_session, user_id)

    today = date.today()

    with patch("app.services.report_service._get_s3_client") as mock_s3:
        mock_s3.return_value = MagicMock(put_object=MagicMock(return_value={}))

        r1 = await generate_monthly_report(db_session, user_id, today.year, today.month)
        r2 = await generate_monthly_report(db_session, user_id, today.year, today.month)

    # Same primary key — upsert, not insert
    assert r1.id == r2.id


@pytest.mark.anyio
async def test_generate_monthly_report_s3_failure_still_creates_record(
    db_session: AsyncSession, client: AsyncClient
):
    """If S3 upload fails, the MonthlyReport record is still created (no s3_key)."""
    headers = await _auth_headers(client)
    user_id = await _get_user_id(headers)
    await _seed_transactions(db_session, user_id)

    today = date.today()

    with patch("app.services.report_service._get_s3_client") as mock_s3:
        mock_s3.return_value.put_object.side_effect = Exception("S3 unavailable")

        report = await generate_monthly_report(db_session, user_id, today.year, today.month)

    assert report is not None
    assert report.s3_key is None


@pytest.mark.anyio
async def test_get_user_reports_empty(db_session: AsyncSession, client: AsyncClient):
    """get_user_reports returns an empty list when no reports exist."""
    headers = await _auth_headers(client)
    user_id = await _get_user_id(headers)

    reports = await get_user_reports(db_session, user_id)
    assert reports == []


@pytest.mark.anyio
async def test_get_user_reports_newest_first(db_session: AsyncSession, client: AsyncClient):
    """Reports are returned newest month first."""
    headers = await _auth_headers(client)
    user_id = await _get_user_id(headers)

    with patch("app.services.report_service._get_s3_client") as mock_s3:
        mock_s3.return_value = MagicMock(put_object=MagicMock(return_value={}))

        for month in [1, 2, 3]:
            await generate_monthly_report(db_session, user_id, 2025, month)

    reports = await get_user_reports(db_session, user_id)
    months = [r.report_month.month for r in reports]
    assert months == [3, 2, 1]


@pytest.mark.anyio
async def test_get_report_download_url_not_found(db_session: AsyncSession, client: AsyncClient):
    """get_report_download_url raises ValueError for unknown report_id."""
    headers = await _auth_headers(client)
    user_id = await _get_user_id(headers)

    with pytest.raises(ValueError, match="not found"):
        await get_report_download_url(db_session, uuid.uuid4(), user_id)


@pytest.mark.anyio
async def test_mark_email_sent(db_session: AsyncSession, client: AsyncClient):
    """mark_email_sent updates email_sent and email_sent_at fields."""
    headers = await _auth_headers(client)
    user_id = await _get_user_id(headers)
    await _seed_transactions(db_session, user_id)

    today = date.today()

    with patch("app.services.report_service._get_s3_client") as mock_s3:
        mock_s3.return_value = MagicMock(put_object=MagicMock(return_value={}))
        report = await generate_monthly_report(db_session, user_id, today.year, today.month)

    assert report.email_sent is False
    await mark_email_sent(db_session, report)
    assert report.email_sent is True
    assert report.email_sent_at is not None


# ── email_service tests ───────────────────────────────────────

@pytest.mark.anyio
async def test_send_monthly_report_email_calls_ses():
    """send_monthly_report_email should call SES send_email with correct params."""
    overview = {
        "income": 4000.0,
        "expenses": 1880.0,
        "net": 2120.0,
        "savings_rate": 0.53,
        "anomaly_count": 0,
    }
    by_category = [
        {"category": "Housing", "total": 1500.0, "count": 1, "percentage": 79.79},
        {"category": "Food",    "total": 300.0,  "count": 1, "percentage": 15.96},
    ]

    with patch("app.services.email_service._get_ses_client") as mock_ses:
        mock_client = MagicMock()
        mock_client.send_email.return_value = {"MessageId": "test-id"}
        mock_ses.return_value = mock_client

        await send_monthly_report_email(
            to_email="user@example.com",
            user_name="Jane Doe",
            month_name="January 2025",
            overview=overview,
            by_category=by_category,
            health_score=72,
            download_url="https://s3.example.com/report.html",
        )

    mock_client.send_email.assert_called_once()
    call_kwargs = mock_client.send_email.call_args[1]
    assert call_kwargs["Destination"]["ToAddresses"] == ["user@example.com"]
    assert "January 2025" in call_kwargs["Message"]["Subject"]["Data"]
    # HTML body should contain the health score
    html_body = call_kwargs["Message"]["Body"]["Html"]["Data"]
    assert "72" in html_body


@pytest.mark.anyio
async def test_send_monthly_report_email_ses_failure_raises():
    """A SES exception should propagate so the caller can handle it."""
    overview = {
        "income": 1000.0, "expenses": 500.0, "net": 500.0,
        "savings_rate": 0.5, "anomaly_count": 0,
    }

    with patch("app.services.email_service._get_ses_client") as mock_ses:
        mock_ses.return_value.send_email.side_effect = Exception("SES quota exceeded")

        with pytest.raises(Exception, match="SES quota exceeded"):
            await send_monthly_report_email(
                to_email="user@example.com",
                user_name=None,
                month_name="February 2025",
                overview=overview,
                by_category=[],
                health_score=50,
            )


@pytest.mark.anyio
async def test_send_monthly_report_email_null_user_name():
    """user_name=None should default to a fallback derived from the email."""
    overview = {
        "income": 2000.0, "expenses": 1000.0, "net": 1000.0,
        "savings_rate": 0.5, "anomaly_count": 0,
    }

    with patch("app.services.email_service._get_ses_client") as mock_ses:
        mock_client = MagicMock()
        mock_client.send_email.return_value = {"MessageId": "x"}
        mock_ses.return_value = mock_client

        # Should not raise
        await send_monthly_report_email(
            to_email="johndoe@example.com",
            user_name=None,
            month_name="March 2025",
            overview=overview,
            by_category=[],
            health_score=60,
        )

    html = mock_client.send_email.call_args[1]["Message"]["Body"]["Html"]["Data"]
    # Falls back to capitalised local part: "Johndoe"
    assert "Johndoe" in html or "johndoe" in html.lower()


# ── API endpoint tests ────────────────────────────────────────

@pytest.mark.anyio
async def test_list_reports_empty(client: AsyncClient):
    """GET /reports/ returns [] when user has no reports."""
    headers = await _auth_headers(client)
    resp = await client.get("/api/v1/reports/", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.anyio
async def test_generate_report_endpoint(
    client: AsyncClient, db_session: AsyncSession
):
    """POST /reports/generate creates a report and returns ReportOut."""
    headers = await _auth_headers(client)
    user_id = await _get_user_id(headers)
    await _seed_transactions(db_session, user_id)

    today = date.today()

    with patch("app.services.report_service._get_s3_client") as mock_s3:
        mock_s3.return_value = MagicMock(put_object=MagicMock(return_value={}))

        resp = await client.post(
            "/api/v1/reports/generate",
            headers=headers,
            json={"year": today.year, "month": today.month},
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["health_score"] is not None
    assert data["total_income"] is not None
    assert "report_month" in data


@pytest.mark.anyio
async def test_generate_report_listed_afterwards(
    client: AsyncClient, db_session: AsyncSession
):
    """After POST /generate, GET /reports/ should include the new report."""
    headers = await _auth_headers(client)
    user_id = await _get_user_id(headers)
    await _seed_transactions(db_session, user_id)

    today = date.today()

    with patch("app.services.report_service._get_s3_client") as mock_s3:
        mock_s3.return_value = MagicMock(put_object=MagicMock(return_value={}))

        await client.post(
            "/api/v1/reports/generate",
            headers=headers,
            json={"year": today.year, "month": today.month},
        )

    resp = await client.get("/api/v1/reports/", headers=headers)
    assert resp.status_code == 200
    reports = resp.json()
    assert len(reports) == 1
    assert reports[0]["health_score"] is not None


@pytest.mark.anyio
async def test_download_report_not_found(client: AsyncClient):
    """GET /reports/{random_id}/download returns 404 for unknown report."""
    headers = await _auth_headers(client)
    resp = await client.get(f"/api/v1/reports/{uuid.uuid4()}/download", headers=headers)
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_resend_report_not_found(client: AsyncClient):
    """POST /reports/{random_id}/resend returns 404 for unknown report."""
    headers = await _auth_headers(client)
    resp = await client.post(f"/api/v1/reports/{uuid.uuid4()}/resend", headers=headers)
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_resend_report_sends_email(
    client: AsyncClient, db_session: AsyncSession
):
    """POST /reports/{id}/resend triggers email delivery and returns 202."""
    headers = await _auth_headers(client)
    user_id = await _get_user_id(headers)
    await _seed_transactions(db_session, user_id)

    today = date.today()

    with patch("app.services.report_service._get_s3_client") as mock_s3:
        mock_s3.return_value = MagicMock(put_object=MagicMock(return_value={}))

        create_resp = await client.post(
            "/api/v1/reports/generate",
            headers=headers,
            json={"year": today.year, "month": today.month},
        )

    report_id = create_resp.json()["id"]

    with patch("app.services.email_service._get_ses_client") as mock_ses:
        mock_ses.return_value.send_email.return_value = {"MessageId": "ok"}

        resp = await client.post(
            f"/api/v1/reports/{report_id}/resend",
            headers=headers,
        )

    assert resp.status_code == 202
    assert "re-sent" in resp.json()["message"]


@pytest.mark.anyio
async def test_reports_require_auth(client: AsyncClient):
    """All report endpoints require a valid JWT."""
    report_id = str(uuid.uuid4())
    for method, url, kwargs in [
        ("get",  "/api/v1/reports/",                         {}),
        ("post", "/api/v1/reports/generate",                 {"json": {}}),
        ("get",  f"/api/v1/reports/{report_id}/download",    {}),
        ("post", f"/api/v1/reports/{report_id}/resend",      {}),
    ]:
        resp = await getattr(client, method)(url, **kwargs)
        assert resp.status_code == 401, f"{method.upper()} {url} should require auth"

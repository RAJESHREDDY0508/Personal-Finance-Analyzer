"""
Integration tests for the statements endpoints.
S3 and Kafka calls are mocked so tests run without AWS credentials.
"""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from tests.test_auth import REGISTER_PAYLOAD

PRESIGNED_STUB = {
    "url": "https://s3.amazonaws.com/bucket",
    "fields": {"key": "statements/test/file.csv", "Content-Type": "text/csv"},
}


async def _auth_headers(client: AsyncClient) -> dict:
    resp = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_upload_requires_auth(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/statements/upload", json={"file_name": "test.csv", "file_type": "csv"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_upload_invalid_file_type(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    resp = await client.post(
        "/api/v1/statements/upload",
        json={"file_name": "test.xls", "file_type": "xls"},
        headers=headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_upload_success_csv(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    with (
        patch("app.api.v1.statements.generate_presigned_upload_url", new_callable=AsyncMock) as mock_s3,
        patch("app.api.v1.statements.kafka_producer.send", new_callable=AsyncMock) as mock_kafka,
    ):
        mock_s3.return_value = PRESIGNED_STUB
        resp = await client.post(
            "/api/v1/statements/upload",
            json={"file_name": "january.csv", "file_type": "csv"},
            headers=headers,
        )
    assert resp.status_code == 201
    data = resp.json()
    assert "statement_id" in data
    assert data["upload_url"] == PRESIGNED_STUB["url"]
    assert data["s3_key"].endswith(".csv")
    mock_s3.assert_called_once()
    mock_kafka.assert_called_once()


@pytest.mark.asyncio
async def test_upload_s3_failure_returns_503(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    with patch(
        "app.api.v1.statements.generate_presigned_upload_url",
        new_callable=AsyncMock,
        side_effect=Exception("S3 unreachable"),
    ):
        resp = await client.post(
            "/api/v1/statements/upload",
            json={"file_name": "fail.csv", "file_type": "csv"},
            headers=headers,
        )
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_upload_kafka_failure_still_returns_201(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    with (
        patch("app.api.v1.statements.generate_presigned_upload_url", new_callable=AsyncMock) as mock_s3,
        patch(
            "app.api.v1.statements.kafka_producer.send",
            new_callable=AsyncMock,
            side_effect=Exception("Kafka down"),
        ),
    ):
        mock_s3.return_value = PRESIGNED_STUB
        resp = await client.post(
            "/api/v1/statements/upload",
            json={"file_name": "test.csv", "file_type": "csv"},
            headers=headers,
        )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_list_statements_empty(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    resp = await client.get("/api/v1/statements", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["statements"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_statements_after_upload(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    with (
        patch("app.api.v1.statements.generate_presigned_upload_url", new_callable=AsyncMock) as mock_s3,
        patch("app.api.v1.statements.kafka_producer.send", new_callable=AsyncMock),
    ):
        mock_s3.return_value = PRESIGNED_STUB
        await client.post(
            "/api/v1/statements/upload",
            json={"file_name": "jan.csv", "file_type": "csv"},
            headers=headers,
        )
    resp = await client.get("/api/v1/statements", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["statements"][0]["file_name"] == "jan.csv"
    assert data["statements"][0]["status"] == "pending"


@pytest.mark.asyncio
async def test_get_statement_not_found(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    import uuid
    resp = await client.get(f"/api/v1/statements/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_statement_success(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    with (
        patch("app.api.v1.statements.generate_presigned_upload_url", new_callable=AsyncMock) as mock_s3,
        patch("app.api.v1.statements.kafka_producer.send", new_callable=AsyncMock),
    ):
        mock_s3.return_value = PRESIGNED_STUB
        upload_resp = await client.post(
            "/api/v1/statements/upload",
            json={"file_name": "q1.csv", "file_type": "csv"},
            headers=headers,
        )
    statement_id = upload_resp.json()["statement_id"]
    resp = await client.get(f"/api/v1/statements/{statement_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == statement_id
    assert resp.json()["file_name"] == "q1.csv"


@pytest.mark.asyncio
async def test_delete_statement(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    with (
        patch("app.api.v1.statements.generate_presigned_upload_url", new_callable=AsyncMock) as mock_s3,
        patch("app.api.v1.statements.kafka_producer.send", new_callable=AsyncMock),
        patch("app.api.v1.statements.delete_object", new_callable=AsyncMock),
    ):
        mock_s3.return_value = PRESIGNED_STUB
        upload_resp = await client.post(
            "/api/v1/statements/upload",
            json={"file_name": "delete_me.csv", "file_type": "csv"},
            headers=headers,
        )
        statement_id = upload_resp.json()["statement_id"]
        del_resp = await client.delete(f"/api/v1/statements/{statement_id}", headers=headers)
    assert del_resp.status_code == 204
    get_resp = await client.get(f"/api/v1/statements/{statement_id}", headers=headers)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_reprocess_statement(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    with (
        patch("app.api.v1.statements.generate_presigned_upload_url", new_callable=AsyncMock) as mock_s3,
        patch("app.api.v1.statements.kafka_producer.send", new_callable=AsyncMock) as mock_kafka,
    ):
        mock_s3.return_value = PRESIGNED_STUB
        upload_resp = await client.post(
            "/api/v1/statements/upload",
            json={"file_name": "retry.csv", "file_type": "csv"},
            headers=headers,
        )
        statement_id = upload_resp.json()["statement_id"]
        mock_kafka.reset_mock()
        reprocess_resp = await client.post(
            f"/api/v1/statements/{statement_id}/reprocess",
            headers=headers,
        )
    assert reprocess_resp.status_code == 200
    assert reprocess_resp.json()["status"] == "pending"
    mock_kafka.assert_called_once()

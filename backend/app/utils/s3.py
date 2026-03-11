"""
AWS S3 helpers — pre-signed URLs, upload, download, delete.
All boto3 calls are run in an executor so they don't block the async event loop.
"""
import asyncio
from functools import lru_cache
from typing import Any

import boto3
import structlog
from botocore.exceptions import ClientError, NoCredentialsError

from app.config import settings

logger = structlog.get_logger(__name__)


@lru_cache(maxsize=1)
def _get_s3_client() -> Any:
    """Return a cached boto3 S3 client.

    Uses explicit credentials only when configured; otherwise falls back to
    the EC2 instance role / credential chain (IAM role, env vars, etc.).
    """
    kwargs: dict[str, Any] = {"region_name": settings.aws_region}
    if settings.aws_access_key_id:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
    if settings.aws_secret_access_key:
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.client("s3", **kwargs)


def _run_sync(func):
    """Run a synchronous boto3 function in the default thread pool."""
    return asyncio.get_event_loop().run_in_executor(None, func)


# ── Pre-signed URLs ───────────────────────────────────────────

async def generate_presigned_upload_url(
    key: str,
    content_type: str,
    expires_in: int = 3600,
) -> dict[str, Any]:
    """
    Generate a pre-signed POST response dict for direct S3 browser upload.
    Returns {"url": str, "fields": dict} — pass both to the client.
    """
    client = _get_s3_client()
    bucket = settings.s3_statements_bucket

    def _call() -> dict:
        return client.generate_presigned_post(
            Bucket=bucket,
            Key=key,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, 50 * 1024 * 1024],  # max 50 MB
            ],
            ExpiresIn=expires_in,
        )

    try:
        result = await _run_sync(_call)
        logger.debug("Pre-signed upload URL generated", key=key)
        return result
    except (ClientError, NoCredentialsError) as exc:
        logger.error("Failed to generate pre-signed URL", error=str(exc))
        raise


async def generate_presigned_download_url(
    key: str,
    expires_in: int = 3600,
) -> str:
    """Generate a pre-signed GET URL for downloading a file from S3."""
    client = _get_s3_client()
    bucket = settings.s3_statements_bucket

    def _call() -> str:
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    try:
        url: str = await _run_sync(_call)
        return url
    except (ClientError, NoCredentialsError) as exc:
        logger.error("Failed to generate download URL", error=str(exc))
        raise


# ── File operations ───────────────────────────────────────────

async def download_file(key: str) -> bytes:
    """Download a file from the statements S3 bucket. Returns raw bytes."""
    client = _get_s3_client()
    bucket = settings.s3_statements_bucket

    def _call() -> bytes:
        response = client.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()

    try:
        data: bytes = await _run_sync(_call)
        logger.debug("File downloaded from S3", key=key, size=len(data))
        return data
    except ClientError as exc:
        logger.error("S3 download failed", key=key, error=str(exc))
        raise


async def delete_object(key: str) -> None:
    """Delete a file from the statements S3 bucket."""
    client = _get_s3_client()
    bucket = settings.s3_statements_bucket

    def _call() -> None:
        client.delete_object(Bucket=bucket, Key=key)

    try:
        await _run_sync(_call)
        logger.info("S3 object deleted", key=key)
    except ClientError as exc:
        logger.warning("S3 delete failed (non-fatal)", key=key, error=str(exc))

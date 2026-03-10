"""
SQS message producer — replaces app/kafka/producer.py.

Uses boto3 (sync) wrapped in asyncio.to_thread so it doesn't block
the event loop. No persistent connection needed — SQS is stateless.
"""
import asyncio
import json
import uuid
from datetime import datetime

import boto3
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


def _serialize(obj: object) -> str:
    """JSON serializer for UUID and datetime."""
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _get_sqs_client() -> "boto3.client":
    """Return a boto3 SQS client using settings credentials."""
    kwargs: dict = {"region_name": settings.aws_region}
    if settings.aws_access_key_id:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
    if settings.aws_secret_access_key:
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.client("sqs", **kwargs)


class SQSProducer:
    """
    Sends JSON messages to SQS queues.

    Drop-in replacement for KafkaProducer.send() — identical call signature
    except `topic` is renamed `queue_url` and `key` is not supported
    (SQS doesn't have partition keys; use MessageGroupId for FIFO queues).
    """

    async def send(self, queue_url: str, payload: dict, key: str | None = None) -> None:
        """
        Publish a message to the given SQS queue URL.

        Args:
            queue_url: Full SQS queue URL (from settings.sqs_* fields).
            payload:   Dict that will be JSON-serialized as MessageBody.
            key:       Ignored (kept for API compatibility with Kafka producer).
        """
        if not queue_url:
            logger.warning("SQS send skipped — queue_url is empty", payload_keys=list(payload.keys()))
            return

        body = json.dumps(payload, default=_serialize)

        def _send_sync() -> None:
            client = _get_sqs_client()
            client.send_message(QueueUrl=queue_url, MessageBody=body)

        await asyncio.to_thread(_send_sync)
        queue_name = queue_url.rstrip("/").split("/")[-1]
        logger.debug("SQS message sent", queue=queue_name)


# Singleton — imported by route handlers and workers
sqs_producer = SQSProducer()

"""
Base SQS consumer worker — replaces the Kafka (AIOKafka) version.

Workers long-poll their SQS queue in a loop.  Each message is:
  • decoded from JSON
  • handed to process_message()
  • deleted from the queue on success

On failure the message is NOT deleted — it becomes visible again after the
queue's visibility timeout and is retried up to maxReceiveCount (3) times
before landing in the companion DLQ.
"""
import asyncio
import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import ClassVar

import boto3
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


def _get_sqs_client() -> "boto3.client":
    kwargs: dict = {"region_name": settings.aws_region}
    if settings.aws_access_key_id:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
    if settings.aws_secret_access_key:
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.client("sqs", **kwargs)


class BaseWorker(ABC):
    """
    Abstract base for SQS long-polling workers.

    Subclasses must define:
        queue_url_fn: ClassVar[Callable[[], str]]   — zero-arg callable that
                                                       returns the queue URL
    and implement:
        async process_message(payload: dict) -> None

    The legacy Kafka class-vars (topic / group_id) are kept with empty defaults
    so that any reference to them in existing subclass code still compiles.
    """

    queue_url_fn: ClassVar[Callable[[], str]]

    # Kept for backwards-compat — unused by the SQS polling loop
    topic: ClassVar[str] = ""
    group_id: ClassVar[str] = ""

    async def start(self) -> None:
        queue_url = self.queue_url_fn()
        class_name = type(self).__name__

        if not queue_url:
            logger.warning(
                "Worker disabled — queue_url is empty",
                worker=class_name,
            )
            return

        queue_name = queue_url.rstrip("/").split("/")[-1]
        logger.info("Worker started", worker=class_name, queue=queue_name)

        while True:
            # ── Receive ──────────────────────────────────────────────
            try:
                response = await asyncio.to_thread(
                    lambda: _get_sqs_client().receive_message(
                        QueueUrl=queue_url,
                        MaxNumberOfMessages=10,
                        WaitTimeSeconds=20,       # long-poll — reduces empty responses
                        AttributeNames=["All"],
                    )
                )
            except Exception as exc:
                logger.error(
                    "SQS receive_message error — backing off 5 s",
                    worker=class_name,
                    error=str(exc),
                )
                await asyncio.sleep(5)
                continue

            # ── Process each message ─────────────────────────────────
            for msg in response.get("Messages", []):
                receipt_handle: str = msg["ReceiptHandle"]
                message_id: str = msg.get("MessageId", "")
                try:
                    payload = json.loads(msg["Body"])
                    await self.process_message(payload)
                    # Delete only on success
                    await asyncio.to_thread(
                        lambda rh=receipt_handle: _get_sqs_client().delete_message(
                            QueueUrl=queue_url,
                            ReceiptHandle=rh,
                        )
                    )
                except Exception as exc:
                    logger.error(
                        "Message processing failed — will retry via visibility timeout",
                        worker=class_name,
                        queue=queue_name,
                        message_id=message_id,
                        error=str(exc),
                    )
                    # Do NOT delete — SQS will re-deliver after visibility timeout
                    # After maxReceiveCount (3) failures it moves to the DLQ

    @abstractmethod
    async def process_message(self, payload: dict) -> None:
        """Process a single SQS message payload (already JSON-decoded)."""
        ...

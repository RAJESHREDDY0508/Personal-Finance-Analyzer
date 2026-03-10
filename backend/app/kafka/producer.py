"""
Singleton AIOKafka producer.
Started during FastAPI lifespan startup, stopped on shutdown.
"""
import json
import uuid
from datetime import datetime

import structlog
from aiokafka import AIOKafkaProducer

from app.config import settings

logger = structlog.get_logger(__name__)


def _json_serializer(value: dict) -> bytes:
    """Serialize dict to JSON bytes, handling UUID and datetime."""
    def default(obj: object) -> str:
        if isinstance(obj, uuid.UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    return json.dumps(value, default=default).encode("utf-8")


class KafkaProducer:
    """
    Thin wrapper around AIOKafkaProducer.
    Provides a simple `send` method for publishing events.
    """

    def __init__(self) -> None:
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            value_serializer=_json_serializer,
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            acks="all",                    # Wait for all replicas to confirm
            enable_idempotence=True,       # Exactly-once delivery
            compression_type="gzip",
        )
        await self._producer.start()
        logger.info("Kafka producer started", servers=settings.kafka_bootstrap_servers)

    async def stop(self) -> None:
        if self._producer:
            await self._producer.stop()
            logger.info("Kafka producer stopped")

    async def send(self, topic: str, payload: dict, key: str | None = None) -> None:
        """Publish a message to a Kafka topic."""
        if self._producer is None:
            raise RuntimeError("Kafka producer is not started")
        await self._producer.send_and_wait(topic, value=payload, key=key)
        logger.debug("Kafka message sent", topic=topic, key=key)


# Singleton instance — imported by route handlers
kafka_producer = KafkaProducer()

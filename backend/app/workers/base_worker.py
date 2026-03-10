"""
Base Kafka consumer worker.
All workers inherit from this class for consistent start/stop/error handling.
"""
import json
import structlog
from abc import ABC, abstractmethod

from aiokafka import AIOKafkaConsumer

from app.config import settings

logger = structlog.get_logger(__name__)


class BaseWorker(ABC):
    """
    Abstract base for Kafka consumer workers.
    Subclasses must implement `process_message`.
    """

    topic: str
    group_id: str

    def __init__(self) -> None:
        self._consumer: AIOKafkaConsumer | None = None

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            self.topic,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=self.group_id,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            auto_offset_reset="earliest",
            enable_auto_commit=False,       # Manual commit after processing
        )
        await self._consumer.start()
        logger.info("Worker started", topic=self.topic, group=self.group_id)

        try:
            async for message in self._consumer:
                try:
                    await self.process_message(message.value)
                    await self._consumer.commit()
                except Exception as e:
                    logger.error(
                        "Worker message processing failed",
                        topic=self.topic,
                        error=str(e),
                        payload=message.value,
                    )
                    # Don't commit — message will be redelivered
        finally:
            await self._consumer.stop()
            logger.info("Worker stopped", topic=self.topic)

    @abstractmethod
    async def process_message(self, payload: dict) -> None:
        """Process a single Kafka message payload."""
        ...

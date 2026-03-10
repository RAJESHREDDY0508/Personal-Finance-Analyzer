"""
Anomaly Detector Worker.

Consumes: transactions.categorized
Produces: anomalies.detected

Runs all three detectors (z-score, duplicates, category spikes)
then publishes the results event.
"""
import uuid
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import engine
from app.kafka.producer import kafka_producer
from app.kafka.topics import Topics
from app.services.anomaly_service import run_all_detectors
from app.workers.base_worker import BaseWorker

logger = structlog.get_logger(__name__)


class AnomalyDetectorWorker(BaseWorker):
    topic = Topics.TRANSACTIONS_CATEGORIZED
    group_id = "anomaly-detector-group"

    async def process_message(self, payload: dict) -> None:
        statement_id = uuid.UUID(payload["statement_id"])
        user_id = uuid.UUID(payload["user_id"])
        log = logger.bind(statement_id=str(statement_id))
        log.info("Running anomaly detection")

        AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with AsyncSessionLocal() as db:
            async with db.begin():
                summary = await run_all_detectors(db, user_id, statement_id)

        await kafka_producer.send(
            topic=Topics.ANOMALIES_DETECTED,
            payload={
                "statement_id": str(statement_id),
                "user_id": str(user_id),
                **summary,
            },
            key=str(statement_id),
        )
        log.info("anomalies.detected published", **summary)

"""
Anomaly Detector Worker.

Consumes: transactions.categorized (SQS)
Produces: anomalies.detected       (SQS)

Runs all three detectors (z-score, duplicates, category spikes)
then publishes the results event.
"""
import uuid
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import engine
from app.sqs.producer import sqs_producer
from app.sqs.queues import Queues
from app.services.anomaly_service import run_all_detectors
from app.workers.base_worker import BaseWorker

logger = structlog.get_logger(__name__)


class AnomalyDetectorWorker(BaseWorker):
    queue_url_fn = Queues.transactions_categorized

    async def process_message(self, payload: dict) -> None:
        statement_id = uuid.UUID(payload["statement_id"])
        user_id = uuid.UUID(payload["user_id"])
        log = logger.bind(statement_id=str(statement_id))
        log.info("Running anomaly detection")

        AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with AsyncSessionLocal() as db:
            async with db.begin():
                summary = await run_all_detectors(db, user_id, statement_id)

        await sqs_producer.send(
            queue_url=Queues.anomalies_detected(),
            payload={
                "statement_id": str(statement_id),
                "user_id": str(user_id),
                **summary,
            },
        )
        log.info("anomalies.detected published", **summary)

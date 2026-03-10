"""
AI Categorizer Worker.

Consumes: statement.parsed
Produces: transactions.categorized

For each parsed statement:
  1. Load all uncategorized transactions (category IS NULL)
  2. Send descriptions in batches of 50 to GPT-4o-mini
  3. Persist category + subcategory per transaction
  4. Publish transactions.categorized event for anomaly detector
"""
import uuid

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import engine
from app.kafka.producer import kafka_producer
from app.kafka.topics import Topics
from app.models.transaction import Transaction
from app.services.ai_service import categorize_batch
from app.workers.base_worker import BaseWorker

logger = structlog.get_logger(__name__)

BATCH_SIZE = 50


class AiCategorizerWorker(BaseWorker):
    """Kafka consumer that AI-categorizes newly parsed transactions."""

    topic = Topics.STATEMENT_PARSED
    group_id = "ai-categorizer-group"

    async def process_message(self, payload: dict) -> None:
        statement_id = uuid.UUID(payload["statement_id"])
        user_id_str = payload["user_id"]
        log = logger.bind(statement_id=str(statement_id))
        log.info("Categorizing transactions")

        AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with AsyncSessionLocal() as db:
            # Load uncategorized transactions for this statement
            result = await db.execute(
                select(Transaction).where(
                    Transaction.statement_id == statement_id,
                    Transaction.category.is_(None),
                )
            )
            txns: list[Transaction] = list(result.scalars())

            if not txns:
                log.info("No uncategorized transactions found")
                return

            log.info("Categorizing", count=len(txns))

            # Process in batches to stay within token limits
            for batch_start in range(0, len(txns), BATCH_SIZE):
                batch = txns[batch_start: batch_start + BATCH_SIZE]
                descriptions = [t.description for t in batch]

                try:
                    results = await categorize_batch(descriptions)
                    result_map = {r["index"]: r for r in results}
                except Exception as exc:
                    log.error("Categorization batch failed", error=str(exc))
                    continue

                async with db.begin():
                    for local_idx, txn in enumerate(batch):
                        r = result_map.get(local_idx, {})
                        category = r.get("category", "Other")
                        subcategory = r.get("subcategory", "")

                        await db.execute(
                            update(Transaction)
                            .where(Transaction.id == txn.id)
                            .values(
                                category=category,
                                subcategory=subcategory or None,
                                categorization_source="ai" if r.get("category") else "rule",
                            )
                        )

            await kafka_producer.send(
                topic=Topics.TRANSACTIONS_CATEGORIZED,
                payload={
                    "statement_id": str(statement_id),
                    "user_id": user_id_str,
                    "transaction_count": len(txns),
                },
                key=str(statement_id),
            )
            log.info("transactions.categorized published", count=len(txns))

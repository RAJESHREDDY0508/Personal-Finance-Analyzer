"""
AI Categorizer Worker.

Consumes: statement.parsed        (SQS)
Produces: transactions.categorized (SQS)

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
from app.sqs.producer import sqs_producer
from app.sqs.queues import Queues
from app.models.transaction import Transaction
from app.services.ai_service import categorize_batch
from app.workers.base_worker import BaseWorker

logger = structlog.get_logger(__name__)

BATCH_SIZE = 50


class AiCategorizerWorker(BaseWorker):
    """SQS consumer that AI-categorizes newly parsed transactions."""

    queue_url_fn = Queues.statement_parsed

    async def process_message(self, payload: dict) -> None:
        statement_id = uuid.UUID(payload["statement_id"])
        user_id_str = payload["user_id"]
        log = logger.bind(statement_id=str(statement_id))
        log.info("Categorizing transactions")

        AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        # ── 1. Read uncategorized transactions in its own session ──
        async with AsyncSessionLocal() as db:
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

        # ── 2. Categorize in batches; write with a fresh session each time ──
        total_done = 0
        for batch_start in range(0, len(txns), BATCH_SIZE):
            batch = txns[batch_start: batch_start + BATCH_SIZE]
            descriptions = [t.description for t in batch]

            try:
                results = await categorize_batch(descriptions)
                result_map = {r["index"]: r for r in results}
            except Exception as exc:
                log.error("Categorization batch failed", error=str(exc))
                continue

            # Fresh session per batch — no implicit-transaction conflict
            async with AsyncSessionLocal() as db:
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
            total_done += len(batch)

        # ── 3. Publish to next stage ─────────────────────────────
        await sqs_producer.send(
            queue_url=Queues.transactions_categorized(),
            payload={
                "statement_id": str(statement_id),
                "user_id": user_id_str,
                "transaction_count": total_done,
            },
        )
        log.info("transactions.categorized published", count=total_done)

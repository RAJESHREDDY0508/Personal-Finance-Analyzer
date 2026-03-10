"""
ML predictor worker.

Consumes: transactions.categorized
Action:   Runs ML budget predictions for the user and upserts into budgets table.
"""
from __future__ import annotations

import uuid

import structlog

from app.database import AsyncSessionLocal as async_session_factory
from app.kafka.topics import Topics
from app.services.ml_service import predict_spending_for_user
from app.workers.base_worker import BaseWorker

logger = structlog.get_logger(__name__)


class MlPredictorWorker(BaseWorker):
    topic = Topics.TRANSACTIONS_CATEGORIZED
    group_id = "ml-predictor-group"

    async def process_message(self, payload: dict) -> None:
        user_id_str: str | None = payload.get("user_id")
        if not user_id_str:
            logger.warning("ml_predictor.missing_user_id", payload=payload)
            return

        try:
            user_id = uuid.UUID(user_id_str)
        except ValueError:
            logger.warning("ml_predictor.invalid_user_id", user_id=user_id_str)
            return

        logger.info("ml_predictor.running", user_id=user_id_str)

        async with async_session_factory() as db:
            predictions = await predict_spending_for_user(db, user_id)
            logger.info(
                "ml_predictor.done",
                user_id=user_id_str,
                predictions=len(predictions),
            )

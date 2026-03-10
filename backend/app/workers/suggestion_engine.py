"""
Suggestion engine worker.

Consumes: anomalies.detected
Action:   Generates savings suggestions for the user and persists them.
"""
from __future__ import annotations

import uuid

import structlog

from app.database import AsyncSessionLocal as async_session_factory
from app.kafka.topics import Topics
from app.services.suggestion_service import generate_suggestions_for_user
from app.workers.base_worker import BaseWorker

logger = structlog.get_logger(__name__)


class SuggestionEngineWorker(BaseWorker):
    topic = Topics.ANOMALIES_DETECTED
    group_id = "suggestion-engine-group"

    async def process_message(self, payload: dict) -> None:
        user_id_str: str | None = payload.get("user_id")
        if not user_id_str:
            logger.warning("suggestion_engine.missing_user_id", payload=payload)
            return

        try:
            user_id = uuid.UUID(user_id_str)
        except ValueError:
            logger.warning("suggestion_engine.invalid_user_id", user_id=user_id_str)
            return

        logger.info("suggestion_engine.running", user_id=user_id_str)

        async with async_session_factory() as db:
            suggestions = await generate_suggestions_for_user(db, user_id)
            logger.info(
                "suggestion_engine.done",
                user_id=user_id_str,
                count=len(suggestions),
            )

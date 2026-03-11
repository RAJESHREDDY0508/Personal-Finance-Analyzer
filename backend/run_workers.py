"""
Worker runner — starts all SQS consumer workers concurrently.

Run with:
    python run_workers.py

Each worker runs an infinite long-poll loop inside an asyncio task.
If a single worker crashes, it is restarted after a 5-second backoff
so the other workers keep running.
"""
import asyncio
import logging

import structlog

from app.workers.ai_categorizer import AiCategorizerWorker
from app.workers.anomaly_detector import AnomalyDetectorWorker
from app.workers.ml_predictor import MlPredictorWorker
from app.workers.statement_parser import StatementParserWorker
from app.workers.suggestion_engine import SuggestionEngineWorker

logging.basicConfig(level=logging.INFO)
logger = structlog.get_logger(__name__)

WORKERS = [
    StatementParserWorker,
    AiCategorizerWorker,
    AnomalyDetectorWorker,
    MlPredictorWorker,
    SuggestionEngineWorker,
]


async def run_with_restart(worker_cls) -> None:
    """Run a worker, restarting it on unexpected exit."""
    name = worker_cls.__name__
    while True:
        try:
            logger.info("Starting worker", worker=name)
            await worker_cls().start()
        except Exception as exc:
            logger.error(
                "Worker crashed — restarting in 5 s",
                worker=name,
                error=str(exc),
            )
            await asyncio.sleep(5)


async def main() -> None:
    logger.info("PFA workers starting", count=len(WORKERS))
    tasks = [asyncio.create_task(run_with_restart(w)) for w in WORKERS]
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())

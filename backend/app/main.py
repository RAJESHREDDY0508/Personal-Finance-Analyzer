"""
FastAPI application factory.
Registers routers, middleware, lifespan events (Kafka producer startup/shutdown).
"""
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.v1.router import api_router

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Startup / shutdown logic.
    - Start Kafka producer on startup
    - Close Kafka producer on shutdown
    """
    logger.info("Starting AI Finance Analyzer API", environment=settings.environment)

    # ── Startup ─────────────────────────────────────────────
    try:
        from app.kafka.producer import kafka_producer
        await kafka_producer.start()
        logger.info("Kafka producer started")
    except Exception as e:
        logger.warning("Kafka producer failed to start (non-fatal in dev)", error=str(e))

    yield  # App runs here

    # ── Shutdown ─────────────────────────────────────────────
    try:
        from app.kafka.producer import kafka_producer
        await kafka_producer.stop()
        logger.info("Kafka producer stopped")
    except Exception as e:
        logger.warning("Kafka producer shutdown error", error=str(e))

    logger.info("API shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="AI Personal Finance Analyzer",
        description="AI-powered SaaS platform for personal finance management",
        version="0.1.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── CORS ────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ─────────────────────────────────────────────
    app.include_router(api_router, prefix="/api/v1")

    # ── Health check ────────────────────────────────────────
    @app.get("/health", tags=["Health"])
    async def health_check() -> dict[str, str]:
        return {"status": "ok", "environment": settings.environment}

    return app


app = create_app()

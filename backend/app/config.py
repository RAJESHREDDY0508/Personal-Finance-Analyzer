"""
Application configuration — reads from .env via Pydantic Settings.
All settings are validated at startup; bad config raises immediately.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────
    environment: str = "development"
    secret_key: str = "change-me"

    # ── Database ─────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://pfa_user:pfa_password@localhost:5432/pfa_db"

    # ── JWT ──────────────────────────────────────────────────
    jwt_secret_key: str = "change-me-access"
    jwt_refresh_secret_key: str = "change-me-refresh"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7

    # ── OpenAI ───────────────────────────────────────────────
    openai_api_key: str = ""

    # ── AWS ──────────────────────────────────────────────────
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"
    s3_statements_bucket: str = "pfa-statements-dev"
    s3_reports_bucket: str = "pfa-reports-dev"
    s3_presigned_url_expiry: int = 3600

    # ── SQS Queue URLs (empty → feature disabled in local dev without LocalStack) ──
    sqs_statement_uploaded_url: str = ""
    sqs_statement_parsed_url: str = ""
    sqs_transactions_categorized_url: str = ""
    sqs_anomalies_detected_url: str = ""
    sqs_report_schedule_url: str = ""
    sqs_report_generated_url: str = ""
    sqs_subscription_events_url: str = ""


    # ── Stripe ───────────────────────────────────────────────
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_premium_price_id: str = ""

    # ── SES ──────────────────────────────────────────────────
    ses_sender_email: str = "noreply@example.com"
    ses_sender_name: str = "AI Finance Analyzer"

    # ── Google OAuth ─────────────────────────────────────────
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"

    # ── Frontend ─────────────────────────────────────────────
    frontend_url: str = "http://localhost:3000"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


@lru_cache
def get_settings() -> Settings:
    """Return cached Settings instance (singleton)."""
    return Settings()


settings = get_settings()

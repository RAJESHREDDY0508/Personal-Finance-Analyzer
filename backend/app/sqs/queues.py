"""
SQS queue URL helpers — single source of truth.
Replaces app/kafka/topics.py.

Queue URLs come from environment variables (set from SSM on EC2,
or manually in .env for local development).
"""
from app.config import settings


class Queues:
    """Accessor for all SQS queue URLs, read from settings."""

    @staticmethod
    def statement_uploaded() -> str:
        return settings.sqs_statement_uploaded_url

    @staticmethod
    def statement_parsed() -> str:
        return settings.sqs_statement_parsed_url

    @staticmethod
    def transactions_categorized() -> str:
        return settings.sqs_transactions_categorized_url

    @staticmethod
    def anomalies_detected() -> str:
        return settings.sqs_anomalies_detected_url

    @staticmethod
    def report_schedule() -> str:
        return settings.sqs_report_schedule_url

    @staticmethod
    def report_generated() -> str:
        return settings.sqs_report_generated_url

    @staticmethod
    def subscription_events() -> str:
        return settings.sqs_subscription_events_url

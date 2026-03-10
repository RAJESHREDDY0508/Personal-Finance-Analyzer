"""
Kafka topic name constants.
Single source of truth — used by producers and consumers.
"""


class Topics:
    # Statement lifecycle
    STATEMENT_UPLOADED = "statement.uploaded"
    STATEMENT_PARSED = "statement.parsed"

    # Transaction processing
    TRANSACTIONS_CATEGORIZED = "transactions.categorized"

    # Anomaly & suggestions
    ANOMALIES_DETECTED = "anomalies.detected"

    # Reporting
    REPORT_SCHEDULE = "report.schedule"
    REPORT_GENERATED = "report.generated"

    # Billing
    SUBSCRIPTION_EVENTS = "subscription.events"

"""Initial schema — all 7 tables

Revision ID: 001
Revises:
Create Date: 2026-03-09

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users ──────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("plan", sa.String(20), nullable=False, server_default="free"),
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(255), nullable=True),
        sa.Column("health_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("email_reports", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ── refresh_tokens ─────────────────────────────────────────
    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"])

    # ── bank_statements ────────────────────────────────────────
    op.create_table(
        "bank_statements",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("s3_key", sa.String(500), nullable=False),
        sa.Column("file_type", sa.String(10), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bank_statements_user_id", "bank_statements", ["user_id"])
    op.create_index("ix_bank_statements_status", "bank_statements", ["status"])

    # ── transactions ───────────────────────────────────────────
    op.create_table(
        "transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("statement_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("subcategory", sa.String(100), nullable=True),
        sa.Column("is_income", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("categorization_source", sa.String(30), nullable=True),
        sa.Column("user_category", sa.String(100), nullable=True),
        sa.Column("is_anomaly", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("anomaly_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("anomaly_reason", sa.Text(), nullable=True),
        sa.Column("is_duplicate", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("duplicate_of", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["statement_id"], ["bank_statements.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["duplicate_of"], ["transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transactions_user_id", "transactions", ["user_id"])
    op.create_index("ix_transactions_statement_id", "transactions", ["statement_id"])
    op.create_index("ix_transactions_date", "transactions", ["date"])
    op.create_index("ix_transactions_category", "transactions", ["category"])
    op.create_index("ix_transactions_is_anomaly", "transactions", ["is_anomaly"])
    op.create_index("ix_transactions_is_duplicate", "transactions", ["is_duplicate"])

    # ── budgets ────────────────────────────────────────────────
    op.create_table(
        "budgets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("monthly_limit", sa.Numeric(12, 2), nullable=True),
        sa.Column("predicted_spend", sa.Numeric(12, 2), nullable=True),
        sa.Column("ml_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "category", "month", name="uq_budget_user_category_month"
        ),
    )
    op.create_index("ix_budgets_user_id", "budgets", ["user_id"])

    # ── savings_suggestions ────────────────────────────────────
    op.create_table(
        "savings_suggestions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("suggestion_type", sa.String(50), nullable=False),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("estimated_savings", sa.Numeric(10, 2), nullable=True),
        sa.Column("dismissed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_savings_suggestions_user_id", "savings_suggestions", ["user_id"])

    # ── monthly_reports ────────────────────────────────────────
    op.create_table(
        "monthly_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_month", sa.Date(), nullable=False),
        sa.Column("s3_key", sa.String(500), nullable=True),
        sa.Column("email_sent", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("email_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_income", sa.Numeric(12, 2), nullable=True),
        sa.Column("total_expenses", sa.Numeric(12, 2), nullable=True),
        sa.Column("savings_rate", sa.Numeric(5, 4), nullable=True),
        sa.Column("health_score", sa.Integer(), nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "report_month", name="uq_report_user_month"),
    )
    op.create_index("ix_monthly_reports_user_id", "monthly_reports", ["user_id"])


def downgrade() -> None:
    op.drop_table("monthly_reports")
    op.drop_table("savings_suggestions")
    op.drop_table("budgets")
    op.drop_table("transactions")
    op.drop_table("bank_statements")
    op.drop_table("refresh_tokens")
    op.drop_table("users")

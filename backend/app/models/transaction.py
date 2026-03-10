"""
Transaction ORM model.
Core entity — each row from a bank statement becomes a Transaction.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    statement_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("bank_statements.id", ondelete="SET NULL"),
        index=True,
    )

    # Core fields
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # negative = debit (expense), positive = credit (income)

    # Categorization
    category: Mapped[str | None] = mapped_column(String(100), index=True)
    subcategory: Mapped[str | None] = mapped_column(String(100))
    is_income: Mapped[bool] = mapped_column(Boolean, default=False)
    # ai | rule | user
    categorization_source: Mapped[str | None] = mapped_column(String(30))
    user_category: Mapped[str | None] = mapped_column(String(100))  # user override

    # Anomaly detection
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    anomaly_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    anomaly_reason: Mapped[str | None] = mapped_column(Text)

    # Duplicate detection
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    duplicate_of: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("transactions.id")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="transactions")  # type: ignore[name-defined]
    statement: Mapped["BankStatement"] = relationship(back_populates="transactions")  # type: ignore[name-defined]

    def __repr__(self) -> str:
        return (
            f"<Transaction id={self.id} date={self.date} "
            f"desc='{self.description[:30]}' amount={self.amount}>"
        )

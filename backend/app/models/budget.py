"""
Budget ORM model.
Stores both user-set monthly limits and ML-predicted spending per category.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("user_id", "category", "month", name="uq_budget_user_category_month"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    month: Mapped[date] = mapped_column(Date, nullable=False)              # First day of month
    monthly_limit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2)) # User-set limit
    predicted_spend: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))  # ML prediction
    ml_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))  # 0.0 - 1.0
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Budget user={self.user_id} cat={self.category} month={self.month}>"

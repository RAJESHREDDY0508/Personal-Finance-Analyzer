"""
SavingsSuggestion ORM model.
AI-generated actionable suggestions for improving financial health.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SavingsSuggestion(Base):
    __tablename__ = "savings_suggestions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # reduce_category | cancel_subscription | swap_merchant | general
    suggestion_type: Mapped[str] = mapped_column(String(50), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_savings: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<SavingsSuggestion id={self.id} type={self.suggestion_type} "
            f"savings={self.estimated_savings}>"
        )

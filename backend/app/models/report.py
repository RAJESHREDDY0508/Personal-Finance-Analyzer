"""
MonthlyReport ORM model.
Records generated monthly financial reports and email delivery status.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String,
    UniqueConstraint, Uuid, func
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MonthlyReport(Base):
    __tablename__ = "monthly_reports"
    __table_args__ = (
        UniqueConstraint("user_id", "report_month", name="uq_report_user_month"),
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
    report_month: Mapped[date] = mapped_column(Date, nullable=False)       # First day of month
    s3_key: Mapped[str | None] = mapped_column(String(500))
    email_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Summary data
    total_income: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    total_expenses: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    savings_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))    # 0.0 - 1.0
    health_score: Mapped[int | None] = mapped_column(Integer)

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<MonthlyReport user={self.user_id} month={self.report_month}>"

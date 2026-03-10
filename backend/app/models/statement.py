"""
BankStatement ORM model.
Tracks uploaded CSV/PDF files and their processing status.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class BankStatement(Base):
    __tablename__ = "bank_statements"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)     # csv | pdf
    # pending | processing | completed | failed
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    row_count: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    user: Mapped["User"] = relationship(back_populates="statements")  # type: ignore[name-defined]
    transactions: Mapped[list["Transaction"]] = relationship(  # type: ignore[name-defined]
        back_populates="statement", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<BankStatement id={self.id} file={self.file_name} status={self.status}>"

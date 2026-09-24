"""SQLAlchemy models for brigades and their active worker memberships."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntegerIdMixin


class Brigade(IntegerIdMixin, Base):
    __tablename__ = "brigades"

    name: Mapped[str] = mapped_column(String(100))
    foreman_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    office_id: Mapped[int] = mapped_column(
        ForeignKey("offices.id", ondelete="RESTRICT"), nullable=False
    )
    division_id: Mapped[int] = mapped_column(
        ForeignKey("divisions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("name = btrim(name) AND name <> ''", name="name_not_blank"),
        Index("uq_brigades_name", func.lower(name), unique=True),
        Index("uq_brigades_foreman_id", "foreman_id", unique=True),
    )


class BrigadeMember(Base):
    __tablename__ = "brigade_members"

    brigade_id: Mapped[int] = mapped_column(
        ForeignKey("brigades.id", ondelete="CASCADE"), primary_key=True
    )
    worker_id: Mapped[int] = mapped_column(
        ForeignKey("workers.user_id", ondelete="CASCADE"), primary_key=True
    )

    __table_args__ = (Index("uq_brigade_members_worker_id", "worker_id", unique=True),)

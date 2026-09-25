"""Provenance of imported source rows, their addresses and the import receipts."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntegerIdMixin


class SourceImport(IntegerIdMixin, Base):
    """One applied source file; dry runs are reported but not stored."""

    __tablename__ = "source_imports"

    service_area_id: Mapped[int] = mapped_column(
        ForeignKey("service_areas.id", ondelete="RESTRICT"), index=True
    )
    kind: Mapped[str] = mapped_column(String(10))
    filename: Mapped[str] = mapped_column(String(255))
    file_sha256: Mapped[str] = mapped_column(String(64))
    mapping_version: Mapped[int] = mapped_column(Integer)
    work_date: Mapped[date | None] = mapped_column(Date)
    office_id: Mapped[int | None] = mapped_column(ForeignKey("offices.id", ondelete="RESTRICT"))
    report: Mapped[dict] = mapped_column(JSONB)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("kind IN ('demand', 'control')", name="kind_valid"),
        CheckConstraint("filename = btrim(filename) AND filename <> ''", name="filename_not_blank"),
    )


class SourceAddress(IntegerIdMixin, Base):
    """A source address text of one area and how its coordinates were obtained."""

    __tablename__ = "source_addresses"

    service_area_id: Mapped[int] = mapped_column(
        ForeignKey("service_areas.id", ondelete="RESTRICT")
    )
    raw_address: Mapped[str] = mapped_column(Text)
    location_id: Mapped[int] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(12))
    source: Mapped[str | None] = mapped_column(String(20))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    # An ambiguous geocoder answer is kept for review but never used for routing.
    candidate_latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    candidate_longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('unresolved', 'geocoded', 'ambiguous', 'manual')", name="status_valid"
        ),
        CheckConstraint("raw_address = btrim(raw_address) AND raw_address <> ''", name="raw_set"),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_range"
        ),
        CheckConstraint(
            "(candidate_latitude IS NULL) = (candidate_longitude IS NULL)", name="candidate_pair"
        ),
        Index("uq_source_addresses_area_raw", "service_area_id", "raw_address", unique=True),
    )


class SourceRecord(IntegerIdMixin, Base):
    """The latest result for one external row: a demand ticket, a control row or a brigade."""

    __tablename__ = "source_records"

    import_id: Mapped[int] = mapped_column(
        ForeignKey("source_imports.id", ondelete="RESTRICT"), index=True
    )
    service_area_id: Mapped[int] = mapped_column(
        ForeignKey("service_areas.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(String(10))
    external_id: Mapped[str] = mapped_column(String(200))
    sheet: Mapped[str | None] = mapped_column(String(100))
    row_number: Mapped[int] = mapped_column(Integer)
    bk_type: Mapped[str | None] = mapped_column(String(150))
    bk_status: Mapped[str | None] = mapped_column(String(100))
    hd_type: Mapped[str | None] = mapped_column(String(200))
    raw: Mapped[dict] = mapped_column(JSONB)
    content_sha256: Mapped[str] = mapped_column(String(64))
    ticket_id: Mapped[int | None] = mapped_column(
        ForeignKey("tickets.id", ondelete="RESTRICT"), index=True
    )
    worker_id: Mapped[int | None] = mapped_column(
        ForeignKey("workers.user_id", ondelete="RESTRICT"), index=True
    )
    address_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_addresses.id", ondelete="RESTRICT")
    )
    outcome: Mapped[str] = mapped_column(String(10))
    reason_code: Mapped[str | None] = mapped_column(String(50))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("kind IN ('demand', 'control', 'brigade')", name="kind_valid"),
        CheckConstraint(
            "outcome IN ('created', 'updated', 'unchanged', 'rejected')", name="outcome_valid"
        ),
        CheckConstraint("row_number > 0", name="row_positive"),
        CheckConstraint(
            "external_id = btrim(external_id) AND external_id <> ''", name="external_id_set"
        ),
        Index(
            "uq_source_records_identity",
            "service_area_id",
            "kind",
            "external_id",
            unique=True,
        ),
    )

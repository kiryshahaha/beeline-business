"""Provenance of organizer source files: imports, addresses and per-row records.

Revision ID: 0023
Revises: 0022
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "service_area_id",
            sa.Integer(),
            sa.ForeignKey("service_areas.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("mapping_version", sa.Integer(), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=True),
        sa.Column("office_id", sa.Integer(), sa.ForeignKey("offices.id", ondelete="RESTRICT")),
        sa.Column("report", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("kind IN ('demand', 'control')", name="kind_valid"),
        sa.CheckConstraint(
            "filename = btrim(filename) AND filename <> ''", name="filename_not_blank"
        ),
    )
    op.create_index("ix_source_imports_service_area_id", "source_imports", ["service_area_id"])
    op.create_table(
        "source_addresses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "service_area_id",
            sa.Integer(),
            sa.ForeignKey("service_areas.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("raw_address", sa.Text(), nullable=False),
        sa.Column(
            "location_id",
            sa.Integer(),
            sa.ForeignKey("locations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("source", sa.String(20), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("candidate_latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("candidate_longitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('unresolved', 'geocoded', 'ambiguous', 'manual')", name="status_valid"
        ),
        sa.CheckConstraint(
            "raw_address = btrim(raw_address) AND raw_address <> ''", name="raw_set"
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_range"
        ),
        sa.CheckConstraint(
            "(candidate_latitude IS NULL) = (candidate_longitude IS NULL)", name="candidate_pair"
        ),
    )
    op.create_index("ix_source_addresses_location_id", "source_addresses", ["location_id"])
    op.create_index(
        "uq_source_addresses_area_raw",
        "source_addresses",
        ["service_area_id", "raw_address"],
        unique=True,
    )
    op.create_table(
        "source_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "import_id",
            sa.Integer(),
            sa.ForeignKey("source_imports.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "service_area_id",
            sa.Integer(),
            sa.ForeignKey("service_areas.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("sheet", sa.String(100), nullable=True),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("bk_type", sa.String(150), nullable=True),
        sa.Column("bk_status", sa.String(100), nullable=True),
        sa.Column("hd_type", sa.String(200), nullable=True),
        sa.Column("raw", postgresql.JSONB(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id", ondelete="RESTRICT")),
        sa.Column("worker_id", sa.Integer(), sa.ForeignKey("workers.user_id", ondelete="RESTRICT")),
        sa.Column(
            "address_id", sa.Integer(), sa.ForeignKey("source_addresses.id", ondelete="RESTRICT")
        ),
        sa.Column("outcome", sa.String(10), nullable=False),
        sa.Column("reason_code", sa.String(50), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("kind IN ('demand', 'control', 'brigade')", name="kind_valid"),
        sa.CheckConstraint(
            "outcome IN ('created', 'updated', 'unchanged', 'rejected')", name="outcome_valid"
        ),
        sa.CheckConstraint("row_number > 0", name="row_positive"),
        sa.CheckConstraint(
            "external_id = btrim(external_id) AND external_id <> ''", name="external_id_set"
        ),
    )
    op.create_index("ix_source_records_import_id", "source_records", ["import_id"])
    op.create_index("ix_source_records_ticket_id", "source_records", ["ticket_id"])
    op.create_index("ix_source_records_worker_id", "source_records", ["worker_id"])
    op.create_index(
        "uq_source_records_identity",
        "source_records",
        ["service_area_id", "kind", "external_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("source_records")
    op.drop_table("source_addresses")
    op.drop_table("source_imports")

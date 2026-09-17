"""Persist route snapshots and idempotent import receipts.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "routes",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column(
            "worker_id",
            sa.Integer(),
            sa.ForeignKey("workers.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("route_date", sa.Date(), nullable=False),
        sa.Column("route_number", sa.Integer(), nullable=False),
        sa.Column("geojson", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("route_number > 0", name="number_positive"),
        sa.CheckConstraint(
            "jsonb_typeof(geojson) = 'object' AND geojson ? 'type' AND geojson ? 'features' "
            "AND geojson->>'type' IS NOT NULL "
            "AND geojson->>'type' = 'FeatureCollection' "
            "AND jsonb_typeof(geojson->'features') = 'array'",
            name="geojson_collection",
        ),
    )
    op.create_index(
        "uq_routes_worker_date_number",
        "routes",
        ["worker_id", "route_date", "route_number"],
        unique=True,
    )
    op.create_index("ix_routes_date", "routes", ["route_date"])
    op.create_table(
        "data_imports",
        sa.Column("fingerprint", sa.String(64), primary_key=True),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("data_imports")
    op.drop_table("routes")

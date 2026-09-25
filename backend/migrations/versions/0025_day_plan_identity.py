"""Key the day plan by service area and keep an auditable chain of its revisions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

REASONS = "'plan_applied', 'worker_redirected', 'manual_edit', 'event_replan'"


def upgrade() -> None:
    op.add_column("day_plan_revisions", sa.Column("service_area_id", sa.Integer()))
    op.add_column("day_plan_revisions", sa.Column("plan_id", sa.Uuid()))
    op.add_column(
        "day_plan_revisions",
        sa.Column("reason", sa.String(length=40), server_default="plan_applied", nullable=False),
    )
    op.add_column(
        "day_plan_revisions",
        sa.Column(
            "effective_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column("day_plan_revisions", sa.Column("superseded_at", sa.DateTime(timezone=True)))
    op.add_column("day_plan_revisions", sa.Column("superseded_by_revision", sa.Integer()))
    op.add_column(
        "day_plan_revisions",
        sa.Column(
            "plan_state",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )

    # The administrative district stays only as the origin of the change.
    op.alter_column("day_plan_revisions", "district_id", existing_type=sa.Integer(), nullable=True)
    op.execute(
        """
        UPDATE day_plan_revisions AS r
        SET service_area_id = a.id
        FROM service_areas AS a
        WHERE a.code = 'district_' || r.district_id AND r.service_area_id IS NULL;
        """
    )
    op.execute(
        """
        UPDATE day_plan_revisions
        SET service_area_id = (SELECT id FROM service_areas ORDER BY id LIMIT 1)
        WHERE service_area_id IS NULL;
        """
    )
    # Districts that share one area shared no revision counter before, so renumber the
    # merged history by the order it was written and keep previous_revision consistent.
    op.execute(
        """
        WITH renumbered AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY service_area_id, route_date ORDER BY created_at, id
                ) AS position
            FROM day_plan_revisions
        )
        UPDATE day_plan_revisions AS r
        SET revision = renumbered.position,
            previous_revision = NULLIF(renumbered.position - 1, 0)
        FROM renumbered
        WHERE renumbered.id = r.id;
        """
    )
    op.execute(
        """
        UPDATE day_plan_revisions AS r
        SET effective_at = r.created_at,
            plan_state = COALESCE(r.result, '{}'::jsonb);
        """
    )
    # Exactly one revision per area-day stays current: the newest one.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY service_area_id, route_date ORDER BY revision DESC, id DESC
                ) AS position
            FROM day_plan_revisions
        )
        UPDATE day_plan_revisions AS r
        SET is_current = (ranked.position = 1)
        FROM ranked
        WHERE ranked.id = r.id;
        """
    )
    op.execute(
        """
        UPDATE day_plan_revisions AS r
        SET superseded_at = successor.created_at,
            superseded_by_revision = successor.revision
        FROM day_plan_revisions AS successor
        WHERE successor.service_area_id = r.service_area_id
          AND successor.route_date = r.route_date
          AND successor.revision = r.revision + 1
          AND NOT r.is_current;
        """
    )
    op.alter_column(
        "day_plan_revisions", "service_area_id", existing_type=sa.Integer(), nullable=False
    )

    op.create_foreign_key(
        "fk_day_plan_revisions_service_area_id_service_areas",
        "day_plan_revisions",
        "service_areas",
        ["service_area_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_day_plan_revisions_plan_id_planning_plans",
        "day_plan_revisions",
        "planning_plans",
        ["plan_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "day_plan_revision_reason_known",
        "day_plan_revisions",
        f"reason IN ({REASONS})",
    )
    op.create_check_constraint(
        "day_plan_revision_superseded_consistent",
        "day_plan_revisions",
        "(superseded_at IS NULL) = (superseded_by_revision IS NULL) "
        "AND NOT (is_current AND superseded_at IS NOT NULL)",
    )

    op.drop_index("ix_day_plan_revisions_day", table_name="day_plan_revisions")
    op.drop_index("uq_day_plan_revisions_current", table_name="day_plan_revisions")
    op.create_index(
        "uq_day_plan_revisions_current",
        "day_plan_revisions",
        ["service_area_id", "route_date"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_index(
        "uq_day_plan_revisions_number",
        "day_plan_revisions",
        ["service_area_id", "route_date", "revision"],
        unique=True,
    )
    op.create_index(
        "ix_day_plan_revisions_day",
        "day_plan_revisions",
        ["service_area_id", "route_date", "revision"],
    )


def downgrade() -> None:
    op.drop_index("ix_day_plan_revisions_day", table_name="day_plan_revisions")
    op.drop_index("uq_day_plan_revisions_number", table_name="day_plan_revisions")
    op.drop_index("uq_day_plan_revisions_current", table_name="day_plan_revisions")
    op.drop_constraint(
        "day_plan_revision_superseded_consistent", "day_plan_revisions", type_="check"
    )
    op.drop_constraint("day_plan_revision_reason_known", "day_plan_revisions", type_="check")
    op.drop_constraint(
        "fk_day_plan_revisions_plan_id_planning_plans", "day_plan_revisions", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_day_plan_revisions_service_area_id_service_areas",
        "day_plan_revisions",
        type_="foreignkey",
    )
    # Revisions written after the switch know only the area; restore the district it maps to.
    op.execute(
        """
        UPDATE day_plan_revisions AS r
        SET district_id = split_part(a.code, '_', 2)::integer
        FROM service_areas AS a
        WHERE a.id = r.service_area_id
          AND r.district_id IS NULL
          AND a.code LIKE 'district_%'
          AND split_part(a.code, '_', 2) ~ '^[0-9]+$';
        """
    )
    op.drop_column("day_plan_revisions", "plan_state")
    op.drop_column("day_plan_revisions", "superseded_by_revision")
    op.drop_column("day_plan_revisions", "superseded_at")
    op.drop_column("day_plan_revisions", "effective_at")
    op.drop_column("day_plan_revisions", "reason")
    op.drop_column("day_plan_revisions", "plan_id")
    op.drop_column("day_plan_revisions", "service_area_id")
    op.alter_column("day_plan_revisions", "district_id", existing_type=sa.Integer(), nullable=False)
    op.create_index(
        "uq_day_plan_revisions_current",
        "day_plan_revisions",
        ["district_id", "route_date"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_index(
        "ix_day_plan_revisions_day",
        "day_plan_revisions",
        ["district_id", "route_date", "revision"],
    )

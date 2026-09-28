"""Store the selected brigade on each ticket."""

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("brigade_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_tickets_brigade_id_brigades",
        "tickets",
        "brigades",
        ["brigade_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_tickets_brigade_id", "tickets", ["brigade_id"])

    # Preserve known assignments first, but only when the worker's brigade serves this area.
    op.execute(
        """
        UPDATE tickets AS ticket
        SET brigade_id = member.brigade_id
        FROM brigade_members AS member
        JOIN brigades AS brigade ON brigade.id = member.brigade_id
        JOIN divisions AS division ON division.id = brigade.division_id
        WHERE ticket.assigned_worker_id = member.worker_id
          AND division.service_area_id = COALESCE(
              ticket.service_area_id,
              (
                  SELECT building.service_area_id
                  FROM locations AS location
                  JOIN buildings AS building ON building.id = location.building_id
                  WHERE location.id = ticket.location_id
              )
          )
        """
    )

    # Unassigned historical tickets inherit a brigade only for a unique area match.
    op.execute(
        """
        WITH unique_area_brigades AS (
            SELECT division.service_area_id, MIN(brigade.id) AS brigade_id
            FROM brigades AS brigade
            JOIN divisions AS division ON division.id = brigade.division_id
            GROUP BY division.service_area_id
            HAVING COUNT(*) = 1
        )
        UPDATE tickets AS ticket
        SET brigade_id = unique_area_brigades.brigade_id
        FROM locations AS location
        JOIN buildings AS building ON building.id = location.building_id
        CROSS JOIN unique_area_brigades
        WHERE ticket.location_id = location.id
          AND unique_area_brigades.service_area_id = COALESCE(
              ticket.service_area_id, building.service_area_id
          )
          AND ticket.assigned_worker_id IS NULL
          AND ticket.brigade_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_tickets_brigade_id", table_name="tickets")
    op.drop_constraint("fk_tickets_brigade_id_brigades", "tickets", type_="foreignkey")
    op.drop_column("tickets", "brigade_id")

"""Record equipment consumption per execution cycle and completion event."""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "equipment_movements",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("execution_cycle", sa.Integer(), nullable=False),
        sa.Column("appliance_id", sa.Integer(), nullable=False),
        sa.Column("office_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("movement", sa.String(length=20), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name="fk_equipment_movements_ticket_id_tickets",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["appliance_id"],
            ["appliances.id"],
            name="fk_equipment_movements_appliance_id_appliances",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["office_id"],
            ["offices.id"],
            name="fk_equipment_movements_office_id_offices",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["work_events.id"],
            name="fk_equipment_movements_event_id_work_events",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_equipment_movements"),
        sa.CheckConstraint("execution_cycle > 0", name="execution_cycle_positive"),
        sa.CheckConstraint("quantity > 0", name="quantity_positive"),
        sa.CheckConstraint("movement IN ('consume')", name="movement_valid"),
    )
    op.create_index(
        "uq_equipment_movements_ticket_cycle_appliance_movement",
        "equipment_movements",
        ["ticket_id", "execution_cycle", "appliance_id", "movement"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_equipment_movements_ticket_cycle_appliance_movement",
        table_name="equipment_movements",
    )
    op.drop_table("equipment_movements")

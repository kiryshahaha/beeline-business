"""Add equipment on hand, office kit reserve and the inventory journal

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-24 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def fk(table, column, target, ondelete):
    referred = target.split(".")[0]
    return sa.ForeignKeyConstraint(
        [column], [target], name=f"fk_{table}_{column}_{referred}", ondelete=ondelete
    )


def upgrade() -> None:
    now = sa.text("now()")
    op.create_table(
        "office_kit_reserves",
        sa.Column("office_id", sa.Integer(), nullable=False),
        sa.Column("appliance_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_office_kit_reserves_quantity_positive"),
        fk("office_kit_reserves", "office_id", "offices.id", "RESTRICT"),
        fk("office_kit_reserves", "appliance_id", "appliances.id", "RESTRICT"),
        sa.PrimaryKeyConstraint("office_id", "appliance_id", name="pk_office_kit_reserves"),
    )
    op.create_table(
        "worker_appliances",
        sa.Column("worker_id", sa.Integer(), nullable=False),
        sa.Column("appliance_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_worker_appliances_quantity_positive"),
        fk("worker_appliances", "worker_id", "workers.user_id", "RESTRICT"),
        fk("worker_appliances", "appliance_id", "appliances.id", "RESTRICT"),
        sa.PrimaryKeyConstraint("worker_id", "appliance_id", name="pk_worker_appliances"),
    )
    op.create_table(
        "appliance_operations",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("operation_key", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=True),
        sa.Column("ticket_id", sa.Integer(), nullable=True),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("request", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.CheckConstraint(
            "kind IN ('issue','return','consume','restore')",
            name="ck_appliance_operations_kind_valid",
        ),
        fk("appliance_operations", "worker_id", "users.id", "RESTRICT"),
        fk("appliance_operations", "ticket_id", "tickets.id", "SET NULL"),
        fk("appliance_operations", "actor_id", "users.id", "RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_appliance_operations"),
        sa.UniqueConstraint("operation_key", name="uq_appliance_operations_operation_key"),
    )
    op.create_index("ix_appliance_operations_worker_id", "appliance_operations", ["worker_id"])
    op.create_index("ix_appliance_operations_ticket_id", "appliance_operations", ["ticket_id"])
    op.create_table(
        "appliance_movements",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("operation_id", sa.Integer(), nullable=False),
        sa.Column("appliance_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=True),
        sa.Column("from_office_id", sa.Integer(), nullable=True),
        sa.Column("from_worker_id", sa.Integer(), nullable=True),
        sa.Column("to_office_id", sa.Integer(), nullable=True),
        sa.Column("to_worker_id", sa.Integer(), nullable=True),
        sa.CheckConstraint("quantity > 0", name="ck_appliance_movements_quantity_positive"),
        sa.CheckConstraint(
            "num_nonnulls(from_office_id, from_worker_id) <= 1"
            " AND num_nonnulls(to_office_id, to_worker_id) <= 1"
            " AND num_nonnulls(from_office_id, from_worker_id, to_office_id, to_worker_id) >= 1",
            name="ck_appliance_movements_ends_valid",
        ),
        fk("appliance_movements", "operation_id", "appliance_operations.id", "CASCADE"),
        fk("appliance_movements", "appliance_id", "appliances.id", "RESTRICT"),
        fk("appliance_movements", "ticket_id", "tickets.id", "SET NULL"),
        fk("appliance_movements", "from_office_id", "offices.id", "RESTRICT"),
        fk("appliance_movements", "from_worker_id", "users.id", "RESTRICT"),
        fk("appliance_movements", "to_office_id", "offices.id", "RESTRICT"),
        fk("appliance_movements", "to_worker_id", "users.id", "RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_appliance_movements"),
    )
    op.create_index("ix_appliance_movements_operation_id", "appliance_movements", ["operation_id"])
    op.create_table(
        "ticket_appliance_states",
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("appliance_id", sa.Integer(), nullable=False),
        sa.Column("holder_worker_id", sa.Integer(), nullable=True),
        sa.Column("consumed_operation_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "holder_worker_id IS NOT NULL OR consumed_operation_id IS NOT NULL",
            name="ck_ticket_appliance_states_state_present",
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id", "appliance_id"],
            ["ticket_appliances.ticket_id", "ticket_appliances.appliance_id"],
            name="fk_ticket_appliance_states_ticket_id_ticket_appliances",
            ondelete="CASCADE",
        ),
        fk("ticket_appliance_states", "holder_worker_id", "users.id", "RESTRICT"),
        sa.ForeignKeyConstraint(
            ["consumed_operation_id"],
            ["appliance_operations.id"],
            name="fk_ticket_appliance_states_consumed_operation",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("ticket_id", "appliance_id", name="pk_ticket_appliance_states"),
    )
    # Tickets completed before the journal were already written off by the old code.
    # Recording that fact keeps a later reopen + complete from writing them off twice.
    source = """
        FROM ticket_appliances ta
        JOIN appliances a ON a.id = ta.appliance_id
        JOIN tickets t ON t.id = ta.ticket_id
    """
    completed = "WHERE t.status = 'completed' AND a.type <> 'TOOL'"
    operation = "JOIN appliance_operations o ON o.operation_key = 'migration-0016:ticket:' || t.id"
    op.execute(
        f"""
        INSERT INTO appliance_operations (operation_key, kind, ticket_id, reason, recorded_at)
        SELECT DISTINCT 'migration-0016:ticket:' || t.id, 'consume', t.id,
               'Списано до ведения журнала оборудования', t.updated_at
        {source} {completed}
        """
    )
    op.execute(
        f"""
        INSERT INTO appliance_movements
            (operation_id, appliance_id, quantity, ticket_id, from_office_id)
        SELECT o.id, ta.appliance_id, ta.quantity, ta.ticket_id, ta.office_id
        {source} {operation} {completed}
        """
    )
    op.execute(
        f"""
        INSERT INTO ticket_appliance_states (ticket_id, appliance_id, consumed_operation_id)
        SELECT ta.ticket_id, ta.appliance_id, o.id
        {source} {operation} {completed}
        """
    )


def downgrade() -> None:
    op.drop_table("ticket_appliance_states")
    op.drop_index("ix_appliance_movements_operation_id", table_name="appliance_movements")
    op.drop_table("appliance_movements")
    op.drop_index("ix_appliance_operations_ticket_id", table_name="appliance_operations")
    op.drop_index("ix_appliance_operations_worker_id", table_name="appliance_operations")
    op.drop_table("appliance_operations")
    op.drop_table("worker_appliances")
    op.drop_table("office_kit_reserves")

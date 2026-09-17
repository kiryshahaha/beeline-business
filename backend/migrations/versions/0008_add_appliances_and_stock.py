"""Add appliances, office warehouse stocks, and ticket appliance allocations

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-17 23:05:00.000000

"""

import sqlalchemy as sa
from alembic import op

from app.modules.appliances.enums import ApplianceType

# revision identifiers, used by Alembic.
revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create appliances table
    op.create_table(
        "appliances",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "type",
            sa.Enum(
                ApplianceType,
                values_callable=lambda types: [t.value for t in types],
                native_enum=False,
                create_constraint=True,
                name="appliance_type",
            ),
            nullable=False,
        ),
        sa.Column("unit", sa.String(length=20), server_default="шт", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("name = btrim(name) AND name <> ''", name="name_not_blank"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_appliances_name", "appliances", [sa.text("lower(name)")], unique=True)

    # 2. Create appliance_stocks table
    op.create_table(
        "appliance_stocks",
        sa.Column("office_id", sa.Integer(), nullable=False),
        sa.Column("appliance_id", sa.Integer(), nullable=False),
        sa.Column("stock", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("stock >= 0", name="stock_nonnegative"),
        sa.ForeignKeyConstraint(
            ["office_id"], ["offices.id"], name="fk_appliance_stocks_office_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["appliance_id"],
            ["appliances.id"],
            name="fk_appliance_stocks_appliance_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("office_id", "appliance_id"),
    )

    # 3. Create ticket_appliances table
    op.create_table(
        "ticket_appliances",
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("appliance_id", sa.Integer(), nullable=False),
        sa.Column("office_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("quantity > 0", name="quantity_positive"),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name="fk_ticket_appliances_ticket_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["appliance_id"],
            ["appliances.id"],
            name="fk_ticket_appliances_appliance_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["office_id"],
            ["offices.id"],
            name="fk_ticket_appliances_office_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("ticket_id", "appliance_id"),
    )
    op.create_index(
        "ix_ticket_appliances_office_appliance",
        "ticket_appliances",
        ["office_id", "appliance_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ticket_appliances_office_appliance", table_name="ticket_appliances")
    op.drop_table("ticket_appliances")
    op.drop_table("appliance_stocks")
    op.drop_index("uq_appliances_name", table_name="appliances")
    op.drop_table("appliances")

"""Add the work type reference with organizer time norms

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-18 18:30:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

# Organizer file "Нормативы.xlsx"; names are kept exactly as written there.
WORK_TYPE_NORMS = [
    ("Подключение клиентов Базовая", 20, 60, 10),
    ("Аварий на ТКД", 20, 80, 0),
    ("Дозаказ оборудования", 20, 10, 10),
    ("Локальная заявка/ремонт у клиента", 20, 30, 0),
]


def upgrade() -> None:
    work_types = op.create_table(
        "work_types",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("travel_minutes", sa.Integer(), nullable=False),
        sa.Column("work_minutes", sa.Integer(), nullable=False),
        sa.Column("documents_minutes", sa.Integer(), nullable=False),
        sa.Column(
            "norm_minutes",
            sa.Integer(),
            sa.Computed("travel_minutes + work_minutes + documents_minutes", persisted=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "name = btrim(name) AND name <> ''", name=op.f("ck_work_types_name_not_blank")
        ),
        sa.CheckConstraint(
            "travel_minutes >= 0", name=op.f("ck_work_types_travel_minutes_nonnegative")
        ),
        sa.CheckConstraint(
            "work_minutes >= 0", name=op.f("ck_work_types_work_minutes_nonnegative")
        ),
        sa.CheckConstraint(
            "documents_minutes >= 0", name=op.f("ck_work_types_documents_minutes_nonnegative")
        ),
        sa.CheckConstraint("norm_minutes > 0", name=op.f("ck_work_types_norm_minutes_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_work_types")),
    )
    op.create_index("uq_work_types_name", "work_types", [sa.text("lower(name)")], unique=True)
    op.bulk_insert(
        work_types,
        [
            {
                "name": name,
                "travel_minutes": travel,
                "work_minutes": work,
                "documents_minutes": documents,
            }
            for name, travel, work, documents in WORK_TYPE_NORMS
        ],
    )


def downgrade() -> None:
    op.drop_index("uq_work_types_name", table_name="work_types")
    op.drop_table("work_types")

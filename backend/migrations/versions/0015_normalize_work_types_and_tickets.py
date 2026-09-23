"""Normalize work types, tickets and planning requirements

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-23 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

CANONICAL_TYPES = [
    ("Подключение клиентов Базовая", "connection", "connection", 2),
    ("Аварий на ТКД", "emergency", "emergency", 1),
    ("Дозаказ оборудования", "additional", "additional", 3),
    ("Локальная заявка/ремонт у клиента", "repair", "repair", 3),
]

BASE_SKILLS = [
    "Монтаж ВОЛС",
    "Настройка оборудования",
    "Аварийно-восстановительные работы",
]

KNOWN_ALIASES = {
    "подключение клиентов базовая": "connection",
    "подключение": "connection",
    "настройка сети": "connection",
    "настройка wi-fi": "connection",
    "wi-fi 'настройка'": "connection",
    "подключить точку доступа": "connection",
    "монтаж оборудования": "repair",
    "аварий на ткд": "emergency",
    "авария на ткд": "emergency",
    "авария": "emergency",
    "дозаказ оборудования": "additional",
    "дозаказ": "additional",
    "локальная заявка/ремонт у клиента": "repair",
    "диагностика сети": "repair",
    "проверить кабель": "repair",
    "проверить покрытие wi-fi": "repair",
    "замена оборудования": "repair",
    "замена роутера": "repair",
}


def upgrade() -> None:
    # 1. Update work_types table
    op.add_column("work_types", sa.Column("code", sa.String(50), nullable=True))
    op.add_column(
        "work_types",
        sa.Column("category", sa.String(50), nullable=True, server_default="repair"),
    )
    op.add_column(
        "work_types",
        sa.Column("default_priority", sa.Integer(), nullable=True, server_default="3"),
    )

    # Set canonical work type attributes
    for name, code, category, priority in CANONICAL_TYPES:
        op.execute(
            sa.text(
                """
                UPDATE work_types
                SET code = :code, category = :category, default_priority = :priority
                WHERE lower(name) = lower(:name)
                """
            ).bindparams(name=name, code=code, category=category, priority=priority)
        )

    # Fill any other existing work_types with fallback code
    op.execute(
        sa.text(
            """
            UPDATE work_types
            SET code = lower(regexp_replace(name, '[^a-zA-Z0-9]+', '_', 'g')),
                category = 'repair',
                default_priority = 3
            WHERE code IS NULL
            """
        )
    )

    op.alter_column("work_types", "code", nullable=False)
    op.alter_column("work_types", "category", nullable=False)
    op.alter_column("work_types", "default_priority", nullable=False)

    op.create_index("uq_work_types_code", "work_types", [sa.text("lower(code)")], unique=True)
    op.create_check_constraint(
        op.f("ck_work_types_code_not_blank"), "work_types", "code = btrim(code) AND code <> ''"
    )
    op.create_check_constraint(
        op.f("ck_work_types_category_valid"),
        "work_types",
        "category IN ('emergency', 'connection', 'repair', 'additional')",
    )
    op.create_check_constraint(
        op.f("ck_work_types_default_priority_positive"),
        "work_types",
        "default_priority >= 1",
    )

    # 2. Update tickets table
    op.add_column("tickets", sa.Column("work_type_id", sa.Integer(), nullable=True))
    op.add_column(
        "tickets",
        sa.Column(
            "category",
            sa.Enum(
                "emergency",
                "connection",
                "repair",
                "additional",
                name="ticket_category",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
    )
    op.add_column("tickets", sa.Column("priority", sa.Integer(), nullable=True))
    op.add_column(
        "tickets",
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "tickets", sa.Column("sla_deadline_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "tickets",
        sa.Column(
            "required_transport_type",
            sa.Enum(
                "car",
                "walking",
                "bicycle",
                "public_transport",
                name="ticket_required_transport_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
    )
    op.add_column("tickets", sa.Column("service_duration_source", sa.String(20), nullable=True))

    # Match by exact name first
    op.execute(
        sa.text(
            """
            UPDATE tickets t
            SET work_type_id = wt.id,
                category = wt.category,
                priority = wt.default_priority
            FROM work_types wt
            WHERE lower(t.work_type) = lower(wt.name)
            """
        )
    )

    # Match by aliases
    for alias, code in KNOWN_ALIASES.items():
        op.execute(
            sa.text(
                """
                UPDATE tickets t
                SET work_type_id = wt.id,
                    category = wt.category,
                    priority = wt.default_priority
                FROM work_types wt
                WHERE t.work_type_id IS NULL
                  AND lower(t.work_type) = :alias
                  AND wt.code = :code
                """
            ).bindparams(alias=alias, code=code)
        )

    # Any remaining unmapped tickets? Check and auto-create work_type or raise if unknown
    conn = op.get_bind()
    unmapped = (
        conn.execute(sa.text("SELECT DISTINCT work_type FROM tickets WHERE work_type_id IS NULL"))
        .scalars()
        .all()
    )
    if unmapped:
        # Create work types for these unmapped types so no data is corrupted or lost
        for wt_name in unmapped:
            if wt_name and wt_name.strip():
                clean_name = wt_name.strip()
                res = (
                    conn.execute(
                        sa.text(
                            """
                        INSERT INTO work_types (
                            name, code, category, default_priority,
                            travel_minutes, work_minutes, documents_minutes
                        )
                        VALUES (
                            :name,
                            lower(regexp_replace(:name, '[^a-zA-Z0-9]+', '_', 'g')),
                            'repair', 3, 20, 30, 0
                        )
                        RETURNING id, category, default_priority
                        """
                        ).bindparams(name=clean_name)
                    )
                    .mappings()
                    .one()
                )
                conn.execute(
                    sa.text(
                        """
                        UPDATE tickets
                        SET work_type_id = :wt_id, category = :category, priority = :priority
                        WHERE work_type_id IS NULL AND work_type = :name
                        """
                    ).bindparams(
                        wt_id=res["id"],
                        category=res["category"],
                        priority=res["default_priority"],
                        name=wt_name,
                    )
                )

    # Fallback to connection (id 1 or first available) if still null
    op.execute(
        sa.text(
            """
            UPDATE tickets
            SET work_type_id = (SELECT id FROM work_types ORDER BY id LIMIT 1),
                category = 'repair',
                priority = 3
            WHERE work_type_id IS NULL
            """
        )
    )

    # Populate received_at, category, priority defaults for any NULLs
    op.execute(
        sa.text(
            """
            UPDATE tickets
            SET received_at = COALESCE(created_at, now()),
                category = COALESCE(category, 'repair'),
                priority = COALESCE(priority, 3)
            WHERE received_at IS NULL OR category IS NULL OR priority IS NULL
            """
        )
    )

    # Set SLA deadline for emergency tickets if not set
    op.execute(
        sa.text(
            """
            UPDATE tickets
            SET sla_deadline_at = received_at + interval '24 hours'
            WHERE category = 'emergency' AND sla_deadline_at IS NULL
            """
        )
    )

    # Make new ticket columns non-nullable and add constraints
    op.alter_column("tickets", "work_type_id", nullable=False)
    op.alter_column("tickets", "category", nullable=False)
    op.alter_column("tickets", "priority", nullable=False)
    op.alter_column("tickets", "received_at", nullable=False)
    op.alter_column("tickets", "work_type", nullable=True)

    op.create_foreign_key(
        op.f("fk_tickets_work_type_id_work_types"),
        "tickets",
        "work_types",
        ["work_type_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint("work_type_not_blank", "tickets", type_="check")
    op.create_check_constraint(
        op.f("ck_tickets_work_type_not_blank"),
        "tickets",
        "work_type IS NULL OR (work_type = btrim(work_type) AND work_type <> '')",
    )
    op.create_check_constraint(op.f("ck_tickets_priority_positive"), "tickets", "priority >= 1")
    op.create_check_constraint(
        op.f("ck_tickets_sla_deadline_after_received"),
        "tickets",
        "sla_deadline_at IS NULL OR sla_deadline_at > received_at",
    )
    op.create_check_constraint(
        op.f("ck_tickets_ticket_duration_source"),
        "tickets",
        "service_duration_source IS NULL OR "
        "service_duration_source IN ('ticket_estimate', 'work_norm')",
    )
    op.create_index("ix_tickets_category_priority", "tickets", ["category", "priority"])
    op.create_index("ix_tickets_work_type_id", "tickets", ["work_type_id"])

    # 3. Ensure Base Skills exist
    for skill_name in BASE_SKILLS:
        op.execute(
            sa.text(
                """
                INSERT INTO worker_skills (skill)
                VALUES (:skill)
                ON CONFLICT (skill) DO NOTHING
                """
            ).bindparams(skill=skill_name)
        )

    # 4. Trigger to set work_type_id and defaults on direct raw SQL inserts
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION trg_tickets_set_defaults()
            RETURNS TRIGGER AS $$
            DECLARE
                found_wt RECORD;
            BEGIN
                IF NEW.received_at IS NULL THEN
                    NEW.received_at := COALESCE(NEW.created_at, now());
                END IF;

                IF NEW.work_type_id IS NULL THEN
                    IF NEW.work_type IS NOT NULL AND btrim(NEW.work_type) <> '' THEN
                        SELECT id, category, default_priority
                        INTO found_wt
                        FROM work_types
                        WHERE lower(name) = lower(btrim(NEW.work_type))
                           OR lower(code) = lower(btrim(NEW.work_type))
                        LIMIT 1;

                        IF found_wt.id IS NULL THEN
                            IF lower(NEW.work_type) LIKE '%авар%' THEN
                                SELECT id, category, default_priority INTO found_wt
                                FROM work_types WHERE code = 'emergency' LIMIT 1;
                            ELSIF lower(NEW.work_type) LIKE '%подключ%'
                               OR lower(NEW.work_type) LIKE '%настройк%' THEN
                                SELECT id, category, default_priority INTO found_wt
                                FROM work_types WHERE code = 'connection' LIMIT 1;
                            ELSIF lower(NEW.work_type) LIKE '%дозаказ%' THEN
                                SELECT id, category, default_priority INTO found_wt
                                FROM work_types WHERE code = 'additional' LIMIT 1;
                            ELSE
                                SELECT id, category, default_priority INTO found_wt
                                FROM work_types WHERE code = 'repair' LIMIT 1;
                            END IF;
                        END IF;

                        IF found_wt.id IS NOT NULL THEN
                            NEW.work_type_id := found_wt.id;
                            IF NEW.category IS NULL THEN
                                NEW.category := found_wt.category;
                            END IF;
                            IF NEW.priority IS NULL THEN
                                NEW.priority := found_wt.default_priority;
                            END IF;
                        END IF;
                    END IF;

                    IF NEW.work_type_id IS NULL THEN
                        SELECT id, category, default_priority
                        INTO found_wt
                        FROM work_types
                        ORDER BY id
                        LIMIT 1;

                        IF found_wt.id IS NOT NULL THEN
                            NEW.work_type_id := found_wt.id;
                            IF NEW.category IS NULL THEN
                                NEW.category := found_wt.category;
                            END IF;
                            IF NEW.priority IS NULL THEN
                                NEW.priority := found_wt.default_priority;
                            END IF;
                        END IF;
                    END IF;
                END IF;

                IF NEW.category IS NULL THEN
                    SELECT category INTO NEW.category FROM work_types WHERE id = NEW.work_type_id;
                    IF NEW.category IS NULL THEN
                        NEW.category := 'repair';
                    END IF;
                END IF;

                IF NEW.priority IS NULL THEN
                    SELECT default_priority INTO NEW.priority
                    FROM work_types WHERE id = NEW.work_type_id;
                    IF NEW.priority IS NULL THEN
                        NEW.priority := 3;
                    END IF;
                END IF;

                IF NEW.category = 'emergency' AND NEW.sla_deadline_at IS NULL THEN
                    NEW.sla_deadline_at := NEW.received_at + interval '24 hours';
                END IF;

                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            DROP TRIGGER IF EXISTS trg_tickets_defaults ON tickets;
            CREATE TRIGGER trg_tickets_defaults
            BEFORE INSERT ON tickets
            FOR EACH ROW
            EXECUTE FUNCTION trg_tickets_set_defaults();
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DROP TRIGGER IF EXISTS trg_tickets_defaults ON tickets;
            DROP FUNCTION IF EXISTS trg_tickets_set_defaults();
            """
        )
    )
    op.drop_index("ix_tickets_work_type_id", table_name="tickets")
    op.drop_index("ix_tickets_category_priority", table_name="tickets")
    op.drop_constraint(op.f("ck_tickets_ticket_duration_source"), "tickets", type_="check")
    op.drop_constraint(op.f("ck_tickets_sla_deadline_after_received"), "tickets", type_="check")
    op.drop_constraint(op.f("ck_tickets_priority_positive"), "tickets", type_="check")
    op.drop_constraint(op.f("ck_tickets_work_type_not_blank"), "tickets", type_="check")
    op.drop_constraint(op.f("fk_tickets_work_type_id_work_types"), "tickets", type_="foreignkey")
    op.alter_column("tickets", "work_type", nullable=False)
    op.create_check_constraint(
        "work_type_not_blank", "tickets", "work_type = btrim(work_type) AND work_type <> ''"
    )

    op.drop_column("tickets", "service_duration_source")
    op.drop_column("tickets", "required_transport_type")
    op.drop_column("tickets", "sla_deadline_at")
    op.drop_column("tickets", "received_at")
    op.drop_column("tickets", "priority")
    op.drop_column("tickets", "category")
    op.drop_column("tickets", "work_type_id")

    op.drop_constraint(op.f("ck_work_types_default_priority_positive"), "work_types", type_="check")
    op.drop_constraint(op.f("ck_work_types_category_valid"), "work_types", type_="check")
    op.drop_constraint(op.f("ck_work_types_code_not_blank"), "work_types", type_="check")
    op.drop_index("uq_work_types_code", table_name="work_types")
    op.drop_column("work_types", "default_priority")
    op.drop_column("work_types", "category")
    op.drop_column("work_types", "code")

"""Link legacy tickets only to an exact, unambiguous catalog entry.

Revision ID: 0022
Revises: 0021
"""

import json
import re
import unicodedata
from collections import defaultdict

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def _normalize(value: str | None) -> str:
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split()).casefold()


def _was_created_by_legacy_fallback(work_type: dict, configured_ids: set[int]) -> bool:
    name = work_type["name"]
    generated_code = re.sub(r"[^a-zA-Z0-9]+", "_", name).lower()
    return (
        work_type["id"] not in configured_ids
        and work_type["code"] == generated_code
        and work_type["category"] == "repair"
        and work_type["default_priority"] == 3
        and work_type["travel_minutes"] == 20
        and work_type["work_minutes"] == 30
        and work_type["documents_minutes"] == 0
    )


def upgrade() -> None:
    op.create_table(
        "ticket_work_type_migration_issues",
        sa.Column(
            "ticket_id",
            sa.Integer(),
            sa.ForeignKey("tickets.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("legacy_value", sa.String(100), nullable=True),
        sa.Column("reason", sa.String(40), nullable=False),
        sa.Column("candidate_work_type_ids", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    connection = op.get_bind()
    configured_ids = set(
        connection.execute(sa.text("SELECT work_type_id FROM work_type_planning_rules"))
        .scalars()
        .all()
    )
    work_types = [
        dict(row)
        for row in connection.execute(
            sa.text(
                """
                SELECT id, name, code, category, default_priority,
                       travel_minutes, work_minutes, documents_minutes
                FROM work_types
                ORDER BY id
                """
            )
        )
        .mappings()
        .all()
    ]
    by_name: dict[str, list[dict]] = defaultdict(list)
    for work_type in work_types:
        by_name[_normalize(work_type["name"])].append(work_type)

    work_types_by_id = {item["id"]: item for item in work_types}
    linked = 0
    unresolved = 0
    tickets = connection.execute(
        sa.text("SELECT id, work_type, work_type_id FROM tickets ORDER BY id")
    ).mappings()
    for ticket in tickets:
        legacy_value = ticket["work_type"]
        normalized = _normalize(legacy_value)
        candidates = by_name.get(normalized, [])

        current_id = ticket["work_type_id"]
        current_work_type = work_types_by_id.get(current_id)
        reason = None
        target_id = None
        candidate_ids = [item["id"] for item in candidates]

        if len(candidates) > 1:
            reason = "ambiguous_normalized_name"
            if current_work_type is not None and not _was_created_by_legacy_fallback(
                current_work_type, configured_ids
            ):
                target_id = current_id
        elif current_work_type is not None and not _was_created_by_legacy_fallback(
            current_work_type, configured_ids
        ):
            # A persisted FK is authoritative. Keep it across a catalog rename even if the
            # preserved legacy label no longer matches the current WorkType.name.
            target_id = current_id
            if not normalized:
                reason = "missing_legacy_value"
            elif len(candidates) == 1 and candidates[0]["id"] != current_id:
                reason = "legacy_value_mismatch"
            elif not candidates:
                reason = "legacy_value_mismatch"
        elif len(candidates) == 1 and not _was_created_by_legacy_fallback(
            candidates[0], configured_ids
        ):
            target_id = candidates[0]["id"]
        elif len(candidates) == 1:
            reason = "unverified_legacy_catalog_entry"
        elif not normalized:
            reason = "missing_legacy_value"
        else:
            reason = "unknown_work_type"

        connection.execute(
            sa.text("UPDATE tickets SET work_type_id = :work_type_id WHERE id = :ticket_id"),
            {"work_type_id": target_id, "ticket_id": ticket["id"]},
        )
        if reason:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO ticket_work_type_migration_issues
                        (ticket_id, legacy_value, reason, candidate_work_type_ids)
                    VALUES (:ticket_id, :legacy_value, :reason, CAST(:candidate_ids AS JSON))
                    """
                ),
                {
                    "ticket_id": ticket["id"],
                    "legacy_value": legacy_value,
                    "reason": reason,
                    "candidate_ids": json.dumps(candidate_ids),
                },
            )
            unresolved += 1
        else:
            linked += 1

    print(
        "T02 ticket work-type migration: "
        f"linked={linked}, unresolved={unresolved}; "
        "see ticket_work_type_migration_issues for ticket IDs and source values"
    )

    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION trg_tickets_set_defaults_t02()
            RETURNS TRIGGER AS $$
            DECLARE
                work_type_category TEXT;
                work_type_default_priority INTEGER;
            BEGIN
                IF NEW.received_at IS NULL THEN
                    NEW.received_at := COALESCE(NEW.created_at, now());
                END IF;

                IF NEW.work_type_id IS NOT NULL THEN
                    SELECT category, default_priority
                    INTO work_type_category, work_type_default_priority
                    FROM work_types WHERE id = NEW.work_type_id;
                END IF;

                IF NEW.category IS NULL THEN
                    NEW.category := COALESCE(work_type_category, 'repair');
                END IF;
                IF NEW.priority IS NULL THEN
                    NEW.priority := COALESCE(work_type_default_priority, 3);
                END IF;
                IF NEW.category = 'emergency' AND NEW.sla_deadline_at IS NULL THEN
                    NEW.sla_deadline_at := NEW.received_at + interval '24 hours';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            DROP TRIGGER IF EXISTS trg_tickets_defaults ON tickets;
            CREATE TRIGGER trg_tickets_defaults
            BEFORE INSERT OR UPDATE OF work_type_id, category, priority, received_at
            ON tickets FOR EACH ROW EXECUTE FUNCTION trg_tickets_set_defaults_t02();
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DROP TRIGGER IF EXISTS trg_tickets_defaults ON tickets;
            DROP FUNCTION IF EXISTS trg_tickets_set_defaults_t02();
            CREATE TRIGGER trg_tickets_defaults
            BEFORE INSERT OR UPDATE OF work_type ON tickets
            FOR EACH ROW EXECUTE FUNCTION trg_tickets_set_defaults();
            """
        )
    )
    op.drop_table("ticket_work_type_migration_issues")

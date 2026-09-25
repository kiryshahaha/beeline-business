"""Parameterized SQL for the day timeline. Transaction boundaries belong to the service."""

from datetime import datetime

from sqlalchemy import RowMapping, text
from sqlalchemy.orm import Session

WORKER_COLUMNS_SQL = """
    u.id, u.surname, u.name, u.lastname,
    w.workshift_start, w.workshift_end, w.transport_type, w.is_on_line
"""


def office_exists(session: Session, office_id: int) -> bool:
    return (
        session.execute(
            text("SELECT EXISTS (SELECT 1 FROM offices WHERE id = :office_id)"),
            {"office_id": office_id},
        ).scalar_one()
        is True
    )


def find_brigades(
    session: Session, *, office_id: int | None, foreman_id: int | None
) -> list[RowMapping]:
    conditions = []
    parameters: dict[str, object] = {}
    if office_id is not None:
        conditions.append("b.office_id = :office_id")
        parameters["office_id"] = office_id
    if foreman_id is not None:
        conditions.append("b.foreman_id = :foreman_id")
        parameters["foreman_id"] = foreman_id

    # Only fixed SQL fragments are joined; every value is a bound parameter.
    query = """
        SELECT
            b.id, b.name, b.office_id, o.name AS office_name,
            f.id AS foreman_id, f.surname AS foreman_surname,
            f.name AS foreman_name, f.lastname AS foreman_lastname
        FROM brigades AS b
        JOIN offices AS o ON o.id = b.office_id
        JOIN users AS f ON f.id = b.foreman_id
    """
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY b.id ASC"
    return list(session.execute(text(query), parameters).mappings().all())


def find_brigade_workers(session: Session, brigade_ids: list[int]) -> list[RowMapping]:
    if not brigade_ids:
        return []
    return list(
        session.execute(
            text(f"""
                SELECT bm.brigade_id, {WORKER_COLUMNS_SQL}
                FROM brigade_members AS bm
                JOIN workers AS w ON w.user_id = bm.worker_id
                JOIN users AS u ON u.id = w.user_id
                WHERE bm.brigade_id = ANY(:brigade_ids)
                ORDER BY u.surname, u.name, u.id
            """),
            {"brigade_ids": brigade_ids},
        )
        .mappings()
        .all()
    )


def find_unassigned_workers(session: Session) -> list[RowMapping]:
    return list(
        session.execute(
            text(f"""
                SELECT {WORKER_COLUMNS_SQL}
                FROM workers AS w
                JOIN users AS u ON u.id = w.user_id
                WHERE NOT EXISTS (
                    SELECT 1 FROM brigade_members AS bm WHERE bm.worker_id = w.user_id
                )
                ORDER BY u.surname, u.name, u.id
            """)
        )
        .mappings()
        .all()
    )


def find_planned_tickets(
    session: Session, worker_ids: list[int], day_start: datetime, day_end: datetime
) -> list[RowMapping]:
    if not worker_ids:
        return []
    return list(
        session.execute(
            text("""
                SELECT
                    t.assigned_worker_id AS worker_id, t.id, t.title, t.work_type, t.status,
                    t.planned_start_at, t.planned_end_at
                FROM tickets AS t
                    WHERE t.assigned_worker_id = ANY(:worker_ids)
                  AND t.planned_start_at < :day_end
                  AND t.planned_end_at > :day_start
                ORDER BY t.planned_start_at, t.id
            """),
            {"worker_ids": worker_ids, "day_start": day_start, "day_end": day_end},
        )
        .mappings()
        .all()
    )

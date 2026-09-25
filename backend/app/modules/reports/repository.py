"""Read-only SQL queries used by downloadable reports."""

from collections.abc import Iterable

from sqlalchemy import MappingResult, text
from sqlalchemy.orm import Session

from app.modules.tickets.repository import TICKET_SELECT_SQL

# A server-side cursor hands rows over in batches instead of one list of every ticket.
FETCH_BATCH_ROWS = 500


def _ticket_filters(
    *,
    status: str | None,
    city_id: int | None,
    district_id: int | None,
    brigade_id: int | None,
) -> tuple[str, dict[str, object]]:
    conditions: list[str] = []
    parameters: dict[str, object] = {}
    if status is not None:
        conditions.append("t.status = :status")
        parameters["status"] = status
    if city_id is not None:
        conditions.append("b.city_id = :city_id")
        parameters["city_id"] = city_id
    if district_id is not None:
        conditions.append("b.district_id = :district_id")
        parameters["district_id"] = district_id
    if brigade_id is not None:
        conditions.append("""
            EXISTS (
                SELECT 1
                FROM ticket_assignments AS brigade_assignment
                JOIN brigade_members AS brigade_member
                    ON brigade_member.worker_id = brigade_assignment.worker_id
                WHERE brigade_assignment.ticket_id = t.id
                  AND brigade_member.brigade_id = :brigade_id
            )
        """)
        parameters["brigade_id"] = brigade_id
    return (" WHERE " + " AND ".join(conditions) if conditions else ""), parameters


def count_tickets(session: Session, **filters) -> int:
    where, parameters = _ticket_filters(**filters)
    # The remaining joins of TICKET_SELECT_SQL follow NOT NULL keys and never drop a ticket.
    query = """
        SELECT count(*)
        FROM tickets AS t
        JOIN locations AS l ON l.id = t.location_id
        JOIN buildings AS b ON b.id = l.building_id
    """
    return session.execute(text(query + where), parameters).scalar_one()


def stream_tickets(session: Session, *, limit: int, **filters) -> MappingResult:
    """Matching tickets by ID; the caller reads and closes them inside its transaction."""

    where, parameters = _ticket_filters(**filters)
    return session.execute(
        text(TICKET_SELECT_SQL + where + " ORDER BY t.id ASC LIMIT :row_limit"),
        {**parameters, "row_limit": limit},
        execution_options={"yield_per": FETCH_BATCH_ROWS},
    ).mappings()


def worker_names(session: Session, worker_ids: Iterable[int]) -> dict[int, str]:
    ids = sorted(set(worker_ids))
    if not ids:
        return {}
    rows = session.execute(
        text("SELECT id, surname, name, lastname FROM users WHERE id = ANY(:ids)"),
        {"ids": ids},
    ).mappings()
    return {
        row["id"]: " ".join(part for part in (row["surname"], row["name"], row["lastname"]) if part)
        for row in rows
    }

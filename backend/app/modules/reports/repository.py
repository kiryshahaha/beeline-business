"""Read-only SQL queries used by downloadable reports."""

from sqlalchemy import RowMapping, text
from sqlalchemy.orm import Session

from app.modules.tickets.repository import TICKET_SELECT_SQL


def find_tickets(
    session: Session,
    *,
    status: str | None,
    city_id: int | None,
    district_id: int | None,
    brigade_id: int | None,
) -> list[RowMapping]:
    """Return every matching ticket without the page size used by the list API."""

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
                FROM brigade_members AS brigade_member
                    WHERE brigade_member.worker_id = t.assigned_worker_id
                  AND brigade_member.brigade_id = :brigade_id
            )
        """)
        parameters["brigade_id"] = brigade_id

    query = TICKET_SELECT_SQL
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY t.id ASC"
    return list(session.execute(text(query), parameters).mappings().all())

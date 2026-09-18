"""Parameterized SQL queries for work types."""

from sqlalchemy import RowMapping, text
from sqlalchemy.orm import Session

WORK_TYPE_SELECT_SQL = """
    SELECT id, name, travel_minutes, work_minutes, documents_minutes, norm_minutes
    FROM work_types
"""


def list_work_types(session: Session) -> list[RowMapping]:
    return list(session.execute(text(WORK_TYPE_SELECT_SQL + " ORDER BY id ASC")).mappings().all())


def find_work_type(session: Session, work_type_id: int) -> RowMapping | None:
    return (
        session.execute(
            text(WORK_TYPE_SELECT_SQL + " WHERE id = :work_type_id"),
            {"work_type_id": work_type_id},
        )
        .mappings()
        .one_or_none()
    )

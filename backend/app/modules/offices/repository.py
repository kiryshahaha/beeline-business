"""Parameterized SQL queries for offices."""

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

OFFICE_COLUMNS = """
    o.id,
    o.name,
    o.location_id
"""


def find_office_by_id(session: Session, office_id: int) -> RowMapping | None:
    return (
        session.execute(
            text(f"SELECT {OFFICE_COLUMNS} FROM offices AS o WHERE o.id = :office_id"),
            {"office_id": office_id},
        )
        .mappings()
        .one_or_none()
    )


def list_offices(session: Session) -> list[RowMapping]:
    return list(
        session.execute(
            text(f"SELECT {OFFICE_COLUMNS} FROM offices AS o ORDER BY o.id ASC"),
        )
        .mappings()
        .all()
    )


def add_office(session: Session, name: str, location_id: int) -> int:
    return session.execute(
        text("""
            INSERT INTO offices (name, location_id)
            VALUES (:name, :location_id)
            RETURNING id
        """),
        {"name": name, "location_id": location_id},
    ).scalar_one()

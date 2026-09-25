"""Literal, parameterized SQL for address directory management."""

from sqlalchemy import RowMapping, text
from sqlalchemy.orm import Session


def get_or_create_id(session: Session, find_sql: str, insert_sql: str, parameters: dict) -> int:
    """Execute the literal SQL supplied below; values are always bound separately."""
    existing_id = session.execute(text(find_sql), parameters).scalar_one_or_none()
    if existing_id is not None:
        return existing_id
    return session.execute(text(insert_sql), parameters).scalar_one()


def find_location(session: Session, location_id: int) -> RowMapping | None:
    """Fetch all location details by ID."""
    return (
        session.execute(
            text("""
            SELECT
                l.id,
                c.id AS city_id, c.name AS city,
                sa.id AS service_area_id, COALESCE(d.name, sa.name) AS district,
                s.id AS street_id, s.name AS street,
                b.id AS building_id, b.number AS building_number, b.block,
                l.entrance_id, e.number AS entrance_number,
                l.floor, l.apartment, l.latitude, l.longitude
            FROM locations AS l
            JOIN buildings AS b ON b.id = l.building_id
            JOIN streets AS s ON s.id = b.street_id
            JOIN service_areas AS sa ON sa.id = b.service_area_id
            LEFT JOIN districts AS d ON sa.code = 'district_' || d.id
            JOIN cities AS c ON c.id = s.city_id
            LEFT JOIN entrances AS e ON e.id = l.entrance_id
            WHERE l.id = :location_id
        """),
            {"location_id": location_id},
        )
        .mappings()
        .one_or_none()
    )

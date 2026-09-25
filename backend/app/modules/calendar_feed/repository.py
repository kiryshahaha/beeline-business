"""Parameterized SQL for calendar tokens and feed tickets."""

from datetime import datetime

from sqlalchemy import RowMapping, text
from sqlalchemy.orm import Session

# Upper bound on events in one feed; calendar clients re-download the whole file.
FEED_LIMIT = 1000


def save_token(session: Session, user_id: int, token_hash: str) -> datetime:
    """Create the user's link or replace it, so the previous link stops working."""
    return session.execute(
        text("""
            INSERT INTO calendar_tokens (user_id, token_hash)
            VALUES (:user_id, :token_hash)
            ON CONFLICT (user_id)
            DO UPDATE SET token_hash = EXCLUDED.token_hash, created_at = now()
            RETURNING created_at
        """),
        {"user_id": user_id, "token_hash": token_hash},
    ).scalar_one()


def find_token_created_at(session: Session, user_id: int) -> datetime | None:
    return session.execute(
        text("SELECT created_at FROM calendar_tokens WHERE user_id = :user_id"),
        {"user_id": user_id},
    ).scalar_one_or_none()


def delete_token(session: Session, user_id: int) -> bool:
    return (
        session.execute(
            text("DELETE FROM calendar_tokens WHERE user_id = :user_id"), {"user_id": user_id}
        ).rowcount
        > 0
    )


def find_feed_owner(session: Session, token_hash: str) -> RowMapping | None:
    # Only workers receive assignments, so a token of any other role opens nothing.
    return (
        session.execute(
            text("""
                SELECT u.id, u.surname, u.name
                FROM calendar_tokens AS ct
                JOIN users AS u ON u.id = ct.user_id
                JOIN workers AS w ON w.user_id = u.id
                WHERE ct.token_hash = :token_hash
            """),
            {"token_hash": token_hash},
        )
        .mappings()
        .one_or_none()
    )


def find_feed_tickets(session: Session, worker_id: int, since: datetime) -> list[RowMapping]:
    return list(
        session.execute(
            text("""
                SELECT
                    t.id, t.title, t.description,
                    COALESCE(wt.name, t.work_type) AS work_type,
                    t.work_type_id, t.category, t.priority, t.received_at,
                    t.sla_deadline_at, t.required_transport_type,
                    t.status,
                    t.visit_window_start, t.visit_window_end,
                    t.planned_start_at, t.planned_end_at, t.updated_at,
                    l.id AS location_id,
                    c.id AS city_id, c.name AS city,
                    d.id AS district_id, d.name AS district,
                    s.id AS street_id, s.name AS street,
                    b.id AS building_id, b.number AS building_number, b.block,
                    l.entrance_id, e.number AS entrance_number,
                    l.floor, l.apartment, l.latitude, l.longitude
                FROM ticket_assignments AS ta
                JOIN tickets AS t ON t.id = ta.ticket_id
                LEFT JOIN work_types AS wt ON wt.id = t.work_type_id
                JOIN locations AS l ON l.id = t.location_id
                JOIN buildings AS b ON b.id = l.building_id
                JOIN streets AS s ON s.id = b.street_id
                JOIN cities AS c ON c.id = s.city_id
                JOIN districts AS d ON d.id = b.district_id
                LEFT JOIN entrances AS e ON e.id = l.entrance_id
                WHERE ta.worker_id = :worker_id
                  AND t.planned_start_at IS NOT NULL
                  AND t.planned_end_at >= :since
                ORDER BY t.planned_start_at, t.id
                LIMIT :limit
            """),
            {"worker_id": worker_id, "since": since, "limit": FEED_LIMIT},
        )
        .mappings()
        .all()
    )

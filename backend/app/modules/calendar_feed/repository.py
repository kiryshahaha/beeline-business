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
    # Only active workers receive assignments: another role or an archived account opens
    # nothing, even if a token row survived.
    return (
        session.execute(
            text("""
                SELECT u.id, u.surname, u.name
                FROM calendar_tokens AS ct
                JOIN users AS u ON u.id = ct.user_id
                JOIN workers AS w ON w.user_id = u.id
                WHERE ct.token_hash = :token_hash
                  AND u.role = 'worker'
                  AND u.archived_at IS NULL
            """),
            {"token_hash": token_hash},
        )
        .mappings()
        .one_or_none()
    )


FEED_TICKET_SQL = """
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
                    sa.id AS service_area_id, COALESCE(d.name, sa.name) AS district,
                    s.id AS street_id, s.name AS street,
                    b.id AS building_id, b.number AS building_number, b.block,
                    l.entrance_id, e.number AS entrance_number,
                    l.floor, l.apartment, l.latitude, l.longitude
                FROM tickets AS t
                LEFT JOIN work_types AS wt ON wt.id = t.work_type_id
                JOIN locations AS l ON l.id = t.location_id
                JOIN buildings AS b ON b.id = l.building_id
                JOIN streets AS s ON s.id = b.street_id
                JOIN cities AS c ON c.id = s.city_id
                JOIN service_areas AS sa ON sa.id = b.service_area_id
                LEFT JOIN districts AS d ON sa.code = 'district_' || d.id
                LEFT JOIN entrances AS e ON e.id = l.entrance_id
"""


def find_feed_tickets(
    session: Session,
    worker_id: int,
    *,
    now: datetime,
    since: datetime,
    until: datetime,
    limit: int = FEED_LIMIT,
) -> tuple[list[RowMapping], bool]:
    """The worker's visits in `[since, until)`, nearest future first when there are too many.

    Ordering by start time and cutting at the limit would silently drop the days
    that matter most once a month of history fills the file. Future visits are taken
    first, from the nearest one, and only the remaining room goes to past visits,
    newest first. The second value says whether anything was left out.
    """
    parameters = {
        "worker_id": worker_id,
        "now": now,
        "since": since,
        "until": until,
        "limit": limit + 1,
    }
    rows = list(
        session.execute(
            text(f"""
                WITH candidates AS (
                    {FEED_TICKET_SQL}
                    WHERE t.assigned_worker_id = :worker_id
                      AND t.planned_start_at IS NOT NULL
                      AND t.planned_end_at >= :since
                      AND t.planned_start_at < :until
                )
                SELECT *
                FROM candidates
                ORDER BY (planned_end_at < :now),
                         CASE WHEN planned_end_at >= :now THEN planned_start_at END ASC,
                         planned_start_at DESC,
                         id
                LIMIT :limit
            """),
            parameters,
        )
        .mappings()
        .all()
    )
    truncated = len(rows) > limit
    rows = rows[:limit]
    rows.sort(key=lambda row: (row["planned_start_at"], row["id"]))
    return rows, truncated


def find_released_tickets(session: Session, worker_id: int, since: datetime) -> list[RowMapping]:
    """Tickets taken away from this worker that are not theirs any more.

    A subscribed client may keep an event after it vanishes from the file, so these are
    published once more as cancelled — by UID and time only, without address or
    description, because the ticket no longer belongs to this worker.
    """
    return list(
        session.execute(
            text("""
                SELECT DISTINCT ON (t.id)
                    t.id, t.title,
                    COALESCE(t.planned_start_at, t.visit_window_start) AS planned_start_at,
                    COALESCE(t.planned_end_at, t.visit_window_end) AS planned_end_at,
                    released.occurred_at AS updated_at
                FROM ticket_assignment_events AS released
                JOIN tickets AS t ON t.id = released.ticket_id
                WHERE released.previous_worker_id = :worker_id
                  AND released.occurred_at >= :since
                  AND t.assigned_worker_id IS DISTINCT FROM :worker_id
                ORDER BY t.id, released.occurred_at DESC
                LIMIT :limit
            """),
            {"worker_id": worker_id, "since": since, "limit": FEED_LIMIT},
        )
        .mappings()
        .all()
    )

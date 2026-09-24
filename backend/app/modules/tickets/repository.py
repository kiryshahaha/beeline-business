"""Literal, parameterized SQL. Transaction boundaries are owned by the service."""

from sqlalchemy import RowMapping, text
from sqlalchemy.orm import Session

from app.modules.notifications.enums import NotificationKind

# Shared columns and joins keep single-ticket and list responses identical.
TICKET_SELECT_SQL = """
    SELECT
        t.id, t.location_id, t.service_area_id, t.title, t.description,
        t.work_type, t.work_type_id, t.category, t.priority,
        t.received_at, t.sla_deadline_at, t.required_transport_type, t.service_duration_source,
        t.status,
        CASE
            WHEN t.lifecycle_state = 'waiting_assignment' AND t.status = 'in_progress'
                THEN 'in_progress'
            WHEN t.lifecycle_state = 'waiting_assignment' AND t.status = 'completed'
                THEN 'completed'
            WHEN t.lifecycle_state = 'waiting_assignment' AND t.status = 'wont_fix'
                THEN 'cancelled'
            ELSE t.lifecycle_state
        END AS state,
        t.revision, t.execution_cycle,
        t.actual_started_at, t.actual_completed_at, t.cancel_reason, t.last_event_id,
        t.visit_window_start, t.visit_window_end, t.planned_start_at, t.planned_end_at,
        t.estimated_duration_minutes, t.actual_duration_minutes,
        t.created_at, t.updated_at,
        COALESCE(
            (
                SELECT array_agg(ta.worker_id ORDER BY ta.worker_id)
                FROM ticket_assignments AS ta
                WHERE ta.ticket_id = t.id
            ),
            ARRAY[]::integer[]
        ) AS assignee_ids,
        c.id AS city_id, c.name AS city,
        d.id AS district_id, d.name AS district,
        s.id AS street_id, s.name AS street,
        b.id AS building_id, b.number AS building_number, b.block,
        l.entrance_id, e.number AS entrance_number,
        l.floor, l.apartment, l.latitude, l.longitude
    FROM tickets AS t
    JOIN locations AS l ON l.id = t.location_id
    JOIN buildings AS b ON b.id = l.building_id
    JOIN streets AS s ON s.id = b.street_id
    JOIN cities AS c ON c.id = s.city_id
    JOIN districts AS d ON d.id = b.district_id
    LEFT JOIN entrances AS e ON e.id = l.entrance_id
"""

# Reused by list, detail, and comment access checks; t is always the ticket alias.
FOREMAN_VISIBILITY_SQL = """
    EXISTS (
        SELECT 1
        FROM ticket_assignments AS visible_assignment
        JOIN brigade_members AS visible_member
            ON visible_member.worker_id = visible_assignment.worker_id
        JOIN brigades AS visible_brigade ON visible_brigade.id = visible_member.brigade_id
        WHERE visible_assignment.ticket_id = t.id
          AND visible_brigade.foreman_id = :foreman_id
    )
"""

WORKER_VISIBILITY_SQL = """
    EXISTS (
        SELECT 1
        FROM ticket_assignments AS visible_assignment
        WHERE visible_assignment.ticket_id = t.id
          AND visible_assignment.worker_id = :worker_id
    )
"""


def ticket_exists(session: Session, ticket_id: int, *, foreman_id: int | None = None) -> bool:
    query = "SELECT EXISTS (SELECT 1 FROM tickets AS t WHERE t.id = :ticket_id"
    parameters = {"ticket_id": ticket_id}
    if foreman_id is not None:
        query += " AND " + FOREMAN_VISIBILITY_SQL
        parameters["foreman_id"] = foreman_id
    return session.execute(text(query + ")"), parameters).scalar_one() is True


def find_location_id(session: Session, location_id: int) -> int | None:
    # Keep this location from being deleted while its ticket is being inserted.
    return session.execute(
        text("SELECT id FROM locations WHERE id = :location_id FOR KEY SHARE"),
        {"location_id": location_id},
    ).scalar_one_or_none()


def add_ticket(session: Session, values: dict[str, object]) -> int:
    return session.execute(
        text("""
            INSERT INTO tickets (
                location_id, title, description,
                work_type, work_type_id, category, priority,
                received_at, sla_deadline_at, required_transport_type, service_duration_source,
                status, lifecycle_state,
                visit_window_start, visit_window_end, planned_start_at, planned_end_at,
                estimated_duration_minutes, actual_duration_minutes
            ) VALUES (
                :location_id, :title, :description,
                :work_type, :work_type_id, :category, :priority,
                :received_at, :sla_deadline_at, :required_transport_type, :service_duration_source,
                :status, :lifecycle_state,
                :visit_window_start, :visit_window_end, :planned_start_at, :planned_end_at,
                :estimated_duration_minutes, :actual_duration_minutes
            )
            RETURNING id
        """),
        values,
    ).scalar_one()


def lock_ticket(session: Session, ticket_id: int) -> RowMapping | None:
    return (
        session.execute(
            text("""
                SELECT id, title, status, lifecycle_state, revision, execution_cycle,
                       location_id, service_area_id, visit_window_start, visit_window_end,
                       planned_start_at, planned_end_at
                FROM tickets
                WHERE id = :ticket_id
                FOR UPDATE
            """),
            {"ticket_id": ticket_id},
        )
        .mappings()
        .one_or_none()
    )


def find_worker_ids(session: Session, worker_ids: list[int]) -> set[int]:
    if not worker_ids:
        return set()
    return set(
        session.execute(
            text("SELECT user_id FROM workers WHERE user_id = ANY(:worker_ids)"),
            {"worker_ids": worker_ids},
        )
        .scalars()
        .all()
    )


def find_worker_line_statuses(session: Session, worker_ids: list[int]) -> dict[int, bool]:
    if not worker_ids:
        return {}
    return dict(
        session.execute(
            text("""
                SELECT user_id, is_on_line
                FROM workers
                WHERE user_id = ANY(:worker_ids)
                ORDER BY user_id
                FOR KEY SHARE
            """),
            {"worker_ids": worker_ids},
        ).all()
    )


def replace_assignees(session: Session, ticket_id: int, worker_ids: list[int]) -> set[int]:
    current_ids = set(
        session.execute(
            text("SELECT worker_id FROM ticket_assignments WHERE ticket_id = :ticket_id"),
            {"ticket_id": ticket_id},
        )
        .scalars()
        .all()
    )
    requested_ids = set(worker_ids)
    session.execute(
        text("DELETE FROM ticket_assignments WHERE ticket_id = :ticket_id"),
        {"ticket_id": ticket_id},
    )
    for worker_id in sorted(requested_ids):
        session.execute(
            text("""
                INSERT INTO ticket_assignments (ticket_id, worker_id)
                VALUES (:ticket_id, :worker_id)
            """),
            {"ticket_id": ticket_id, "worker_id": worker_id},
        )
    return requested_ids - current_ids


def is_worker_assigned(session: Session, ticket_id: int, worker_id: int) -> bool:
    return (
        session.execute(
            text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM ticket_assignments
                    WHERE ticket_id = :ticket_id AND worker_id = :worker_id
                )
            """),
            {"ticket_id": ticket_id, "worker_id": worker_id},
        ).scalar_one()
        is True
    )


def list_observer_ids(session: Session) -> list[int]:
    return list(
        session.execute(text("SELECT id FROM users WHERE role = 'observer' ORDER BY id")).scalars()
    )


def update_status(session: Session, ticket_id: int, status: str) -> None:
    session.execute(
        text("""
            UPDATE tickets
            SET status = :status, updated_at = now()
            WHERE id = :ticket_id
        """),
        {"ticket_id": ticket_id, "status": status},
    )


def add_notification_events(
    session: Session,
    recipient_ids: list[int] | set[int],
    *,
    kind: NotificationKind,
    ticket_id: int,
    data: dict[str, object],
) -> None:
    import json

    payload = json.dumps(data, ensure_ascii=False)
    for recipient_id in sorted(recipient_ids):
        session.execute(
            text("""
                INSERT INTO notification_events (recipient_id, ticket_id, kind, data)
                VALUES (:recipient_id, :ticket_id, :kind, CAST(:data AS JSONB))
            """),
            {
                "recipient_id": recipient_id,
                "ticket_id": ticket_id,
                "kind": kind.value,
                "data": payload,
            },
        )


def find_ticket(
    session: Session,
    ticket_id: int,
    *,
    foreman_id: int | None = None,
    worker_id: int | None = None,
) -> RowMapping | None:
    query = TICKET_SELECT_SQL + " WHERE t.id = :ticket_id"
    parameters = {"ticket_id": ticket_id}
    if foreman_id is not None:
        query += " AND " + FOREMAN_VISIBILITY_SQL
        parameters["foreman_id"] = foreman_id
    if worker_id is not None:
        query += " AND " + WORKER_VISIBILITY_SQL
        parameters["worker_id"] = worker_id
    return (
        session.execute(
            text(query),
            parameters,
        )
        .mappings()
        .one_or_none()
    )


def find_tickets(
    session: Session,
    *,
    status: str | None,
    city_id: int | None,
    district_id: int | None,
    limit: int,
    offset: int,
    brigade_id: int | None = None,
    foreman_id: int | None = None,
    worker_id: int | None = None,
) -> list[RowMapping]:
    conditions = []
    parameters: dict[str, object] = {"limit": limit, "offset": offset}
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
                SELECT 1 FROM ticket_assignments AS brigade_assignment
                JOIN brigade_members AS brigade_member
                    ON brigade_member.worker_id = brigade_assignment.worker_id
                WHERE brigade_assignment.ticket_id = t.id
                  AND brigade_member.brigade_id = :brigade_id
            )
        """)
        parameters["brigade_id"] = brigade_id
    if foreman_id is not None:
        conditions.append(FOREMAN_VISIBILITY_SQL)
        parameters["foreman_id"] = foreman_id
    if worker_id is not None:
        conditions.append(WORKER_VISIBILITY_SQL)
        parameters["worker_id"] = worker_id

    # Only fixed SQL fragments are joined; every value is a bound parameter.
    query = TICKET_SELECT_SQL
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY t.id ASC LIMIT :limit OFFSET :offset"
    return list(session.execute(text(query), parameters).mappings().all())

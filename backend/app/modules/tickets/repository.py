"""Literal, parameterized SQL. Transaction boundaries are owned by the service."""

from sqlalchemy import RowMapping, text
from sqlalchemy.orm import Session

from app.modules.notifications.enums import NotificationKind

# Shared columns and joins keep single-ticket and list responses identical.
TICKET_SELECT_SQL = """
    SELECT
        t.id, t.location_id, COALESCE(t.service_area_id, b.service_area_id) AS service_area_id,
        t.brigade_id, COALESCE(ticket_district.name, ticket_area.name) AS district,
        t.title, t.description,
        COALESCE(wt.name, t.work_type) AS work_type,
        t.work_type_id, t.category, t.priority,
        t.received_at, t.sla_deadline_at, t.response_deadline_at, t.intake_source,
        t.request_type_hd,
        t.required_transport_type, t.service_duration_source,
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
        t.assigned_worker_id, t.is_pinned,
        c.id AS city_id, c.name AS city,
        location_area.id AS location_service_area_id,
        COALESCE(location_district.name, location_area.name) AS location_district,
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
    JOIN service_areas AS location_area ON location_area.id = b.service_area_id
    LEFT JOIN districts AS location_district
        ON location_area.code = 'district_' || location_district.id
    LEFT JOIN service_areas AS ticket_area
        ON ticket_area.id = COALESCE(t.service_area_id, b.service_area_id)
    LEFT JOIN districts AS ticket_district
        ON ticket_area.code = 'district_' || ticket_district.id
    LEFT JOIN entrances AS e ON e.id = l.entrance_id
"""

# Reused by list, detail, and comment access checks; t is always the ticket alias.
FOREMAN_VISIBILITY_SQL = """
    (
        EXISTS (
            SELECT 1
            FROM brigades AS target_brigade
            WHERE target_brigade.id = t.brigade_id
              AND target_brigade.foreman_id = :foreman_id
        )
        OR EXISTS (
        SELECT 1
        FROM brigade_members AS visible_member
        JOIN brigades AS visible_brigade ON visible_brigade.id = visible_member.brigade_id
        WHERE visible_member.worker_id = t.assigned_worker_id
          AND visible_brigade.foreman_id = :foreman_id
        )
    )
"""

WORKER_VISIBILITY_SQL = """
    t.assigned_worker_id = :worker_id
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


def find_ticket_geocode_source(session: Session, location_id: int) -> RowMapping | None:
    return (
        session.execute(
            text("""
                SELECT location.latitude, location.longitude, building.service_area_id
                FROM locations AS location
                JOIN buildings AS building ON building.id = location.building_id
                WHERE location.id = :location_id
            """),
            {"location_id": location_id},
        )
        .mappings()
        .one_or_none()
    )


def find_service_area_for_district(
    session: Session, district_name: str, city_name: str | None
) -> int | None:
    statement = """
        SELECT area.id
        FROM districts AS district
        JOIN cities AS city ON city.id = district.city_id
        JOIN service_areas AS area ON area.code = 'district_' || district.id
        WHERE lower(district.name) = lower(:district_name)
    """
    parameters = {"district_name": district_name}
    if city_name:
        city_rows = (
            session.execute(
                text(statement + " AND lower(city.name) = lower(:city_name)"),
                parameters | {"city_name": city_name},
            )
            .scalars()
            .all()
        )
        if len(city_rows) == 1:
            return city_rows[0]
        if city_rows:
            return None

    matches = session.execute(text(statement), parameters).scalars().all()
    return matches[0] if len(matches) == 1 else None


def find_brigade_ids_for_service_area(session: Session, service_area_id: int) -> list[int]:
    return list(
        session.execute(
            text("""
                SELECT brigade.id
                FROM brigades AS brigade
                JOIN divisions AS division ON division.id = brigade.division_id
                WHERE division.service_area_id = :service_area_id
                ORDER BY brigade.id
            """),
            {"service_area_id": service_area_id},
        ).scalars()
    )


def find_brigade_service_area(session: Session, brigade_id: int) -> int | None:
    return session.execute(
        text("""
            SELECT division.service_area_id
            FROM brigades AS brigade
            JOIN divisions AS division ON division.id = brigade.division_id
            WHERE brigade.id = :brigade_id
        """),
        {"brigade_id": brigade_id},
    ).scalar_one_or_none()


def find_worker_brigade_id(session: Session, worker_id: int) -> int | None:
    return session.execute(
        text("SELECT brigade_id FROM brigade_members WHERE worker_id = :worker_id"),
        {"worker_id": worker_id},
    ).scalar_one_or_none()


def lock_ticket_brigade_context(session: Session, ticket_id: int) -> RowMapping | None:
    return (
        session.execute(
            text("""
                SELECT ticket.id, ticket.assigned_worker_id, ticket.brigade_id,
                       COALESCE(ticket.service_area_id, building.service_area_id) AS service_area_id
                FROM tickets AS ticket
                JOIN locations AS location ON location.id = ticket.location_id
                JOIN buildings AS building ON building.id = location.building_id
                WHERE ticket.id = :ticket_id
                FOR UPDATE OF ticket
            """),
            {"ticket_id": ticket_id},
        )
        .mappings()
        .one_or_none()
    )


def update_ticket_brigade(session: Session, ticket_id: int, brigade_id: int | None) -> None:
    session.execute(
        text("""
            UPDATE tickets
            SET brigade_id = :brigade_id, updated_at = now()
            WHERE id = :ticket_id
        """),
        {"ticket_id": ticket_id, "brigade_id": brigade_id},
    )


def add_ticket(session: Session, values: dict[str, object]) -> int:
    params = {
        "response_deadline_at": None,
        "intake_source": None,
        "request_type_hd": None,
        **values,
    }
    return session.execute(
        text("""
            INSERT INTO tickets (
                location_id, service_area_id, brigade_id, title, description,
                work_type, work_type_id, category, priority,
                received_at, sla_deadline_at, response_deadline_at, intake_source, request_type_hd,
                required_transport_type, service_duration_source,
                status, lifecycle_state,
                visit_window_start, visit_window_end, planned_start_at, planned_end_at,
                estimated_duration_minutes, actual_duration_minutes
            ) VALUES (
                :location_id, :service_area_id, :brigade_id, :title, :description,
                :work_type, :work_type_id, :category, :priority,
                :received_at, :sla_deadline_at, :response_deadline_at,
                :intake_source, :request_type_hd,
                :required_transport_type, :service_duration_source,
                :status, :lifecycle_state,
                :visit_window_start, :visit_window_end, :planned_start_at, :planned_end_at,
                :estimated_duration_minutes, :actual_duration_minutes
            )
            RETURNING id
        """),
        params,
    ).scalar_one()


def lock_ticket(session: Session, ticket_id: int) -> RowMapping | None:
    return (
        session.execute(
            text("""
                SELECT id, title, status, lifecycle_state, revision, execution_cycle,
                       location_id, service_area_id, brigade_id,
                       visit_window_start, visit_window_end,
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
            text(
                """
                SELECT w.user_id
                FROM workers AS w
                JOIN users AS u ON u.id = w.user_id
                WHERE w.user_id = ANY(:worker_ids)
                  AND u.role = 'worker'
                  AND u.archived_at IS NULL
                """
            ),
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
                SELECT w.user_id, w.is_on_line
                FROM workers AS w
                JOIN users AS u ON u.id = w.user_id
                -- An archived engineer or a former worker keeps history but gets no new work.
                WHERE w.user_id = ANY(:worker_ids)
                  AND u.role = 'worker'
                  AND u.archived_at IS NULL
                ORDER BY w.user_id
                FOR KEY SHARE OF w
            """),
            {"worker_ids": worker_ids},
        ).all()
    )


def update_assignment(
    session: Session, ticket_id: int, worker_id: int | None, is_pinned: bool = True
) -> tuple[int | None, int | None]:
    old_worker_id = session.execute(
        text("SELECT assigned_worker_id FROM tickets WHERE id = :ticket_id FOR UPDATE"),
        {"ticket_id": ticket_id},
    ).scalar_one()

    session.execute(
        text("""
            UPDATE tickets
            SET assigned_worker_id = :worker_id, is_pinned = :is_pinned, updated_at = now()
            WHERE id = :ticket_id
        """),
        {"ticket_id": ticket_id, "worker_id": worker_id, "is_pinned": is_pinned},
    )
    return old_worker_id, worker_id


def is_worker_assigned(session: Session, ticket_id: int, worker_id: int) -> bool:
    return (
        session.execute(
            text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM tickets
                    WHERE id = :ticket_id AND assigned_worker_id = :worker_id
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
    service_area_id: int | None,
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
    if service_area_id is not None:
        conditions.append("COALESCE(t.service_area_id, b.service_area_id) = :service_area_id")
        parameters["service_area_id"] = service_area_id
    if brigade_id is not None:
        conditions.append("""
            (
                t.brigade_id = :brigade_id OR (
                    t.brigade_id IS NULL AND EXISTS (
                SELECT 1 FROM brigade_members AS brigade_member
                    WHERE brigade_member.worker_id = t.assigned_worker_id
                  AND brigade_member.brigade_id = :brigade_id
                    )
                )
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

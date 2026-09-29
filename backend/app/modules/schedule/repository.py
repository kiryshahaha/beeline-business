from datetime import date, datetime

from sqlalchemy import RowMapping, text
from sqlalchemy.orm import Session

from app.core.workday import MOSCOW

WORKER_COLUMNS_SQL = """
    u.id, u.surname, u.name, u.lastname,
    w.workshift_start, w.workshift_end, w.transport_type, w.is_on_line, w.service_area_id,
    w.schedule_type, w.cycle_start_date, w.workdays_mask
"""

# A ticket's area is its own, or the one of the building it is in.
TICKET_AREA_SQL = "COALESCE(t.service_area_id, ticket_building.service_area_id)"


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
                  AND u.role = 'worker'
                  AND u.archived_at IS NULL
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
                -- A former worker keeps the profile as history; it is not a free engineer.
                WHERE u.role = 'worker'
                  AND u.archived_at IS NULL
                  AND NOT EXISTS (
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
    day = day_start.astimezone(MOSCOW).date()
    return list(
        session.execute(
            text("""
                SELECT
                    t.assigned_worker_id AS worker_id, t.id, t.title, t.work_type, t.status, t.is_pinned,
                    COALESCE(t.planned_start_at, t.visit_window_start) AS planned_start_at,
                    COALESCE(
                        t.planned_end_at,
                        t.visit_window_end,
                        t.visit_window_start + make_interval(mins => COALESCE(t.estimated_duration_minutes, 60))
                    ) AS planned_end_at
                FROM tickets AS t
                WHERE t.assigned_worker_id = ANY(:worker_ids)
                  AND (
                    (t.planned_start_at IS NOT NULL AND t.planned_start_at < :day_end AND t.planned_end_at > :day_start)
                    OR
                    (t.planned_start_at IS NULL AND (t.visit_window_start AT TIME ZONE 'Europe/Moscow')::date = :day)
                  )
                ORDER BY COALESCE(t.planned_start_at, t.visit_window_start), t.id
            """),
            {"worker_ids": worker_ids, "day_start": day_start, "day_end": day_end, "day": day},
        )
        .mappings()
        .all()
    )


def find_worker_day_tickets(
    session: Session, worker_ids: list[int], window_start: datetime, window_end: datetime
) -> list[RowMapping]:
    """Assigned tickets whose promised visit starts inside any of the workers' windows."""
    if not worker_ids:
        return []
    return list(
        session.execute(
            text("""
                SELECT t.assigned_worker_id AS worker_id, t.id,
                       COALESCE(t.planned_start_at, t.visit_window_start) AS planned_start_at,
                       COALESCE(
                           t.planned_end_at,
                           t.visit_window_end,
                           t.visit_window_start + make_interval(mins => COALESCE(t.estimated_duration_minutes, 60))
                       ) AS planned_end_at
                FROM tickets AS t
                WHERE t.assigned_worker_id = ANY(:worker_ids)
                  AND (
                    (t.planned_start_at IS NOT NULL AND t.planned_start_at >= :window_start AND t.planned_start_at < :window_end)
                    OR
                    (t.planned_start_at IS NULL AND t.visit_window_start >= :window_start AND t.visit_window_start < :window_end)
                  )
                ORDER BY COALESCE(t.planned_start_at, t.visit_window_start), t.id
            """),
            {"worker_ids": worker_ids, "window_start": window_start, "window_end": window_end},
        )
        .mappings()
        .all()
    )


def find_latest_routes(session: Session, worker_ids: list[int], day) -> list[RowMapping]:
    """Each worker's newest saved route for the day; older ones are history."""
    if not worker_ids:
        return []
    return list(
        session.execute(
            text("""
                SELECT DISTINCT ON (r.worker_id)
                    r.worker_id, r.id, r.route_number, r.created_at, r.geojson
                FROM routes AS r
                WHERE r.worker_id = ANY(:worker_ids) AND r.route_date = :day
                ORDER BY r.worker_id, r.route_number DESC
            """),
            {"worker_ids": worker_ids, "day": day},
        )
        .mappings()
        .all()
    )


def find_day_states(session: Session, worker_ids: list[int], day) -> list[RowMapping]:
    """Dated availability: the same rows the planner reads to exclude an engineer."""
    if not worker_ids:
        return []
    return list(
        session.execute(
            text("""
                SELECT DISTINCT ON (s.worker_id)
                    s.worker_id, s.available, s.unavailable_at, s.unavailable_until,
                    s.expected_available_at, s.reason
                FROM worker_day_states AS s
                WHERE s.worker_id = ANY(:worker_ids) AND s.route_date = :day
                ORDER BY s.worker_id, s.available ASC, s.id DESC
            """),
            {"worker_ids": worker_ids, "day": day},
        )
        .mappings()
        .all()
    )


def find_shift_exceptions(session: Session, worker_ids: list[int], day: date) -> list[RowMapping]:
    """Dated shift exceptions for workers: overrides for day off or specific shift hours."""
    if not worker_ids:
        return []
    return list(
        session.execute(
            text("""
                SELECT id, worker_id, exception_date, is_working, workshift_start, workshift_end
                FROM worker_shift_exceptions
                WHERE worker_id = ANY(:worker_ids) AND exception_date = :day
            """),
            {"worker_ids": worker_ids, "day": day},
        )
        .mappings()
        .all()
    )


def find_office_areas(session: Session, office_ids: list[int]) -> dict[int, int]:
    """The service area each office serves: its own setting, else its building's area."""
    if not office_ids:
        return {}
    return {
        row["id"]: row["service_area_id"]
        for row in session.execute(
            text("""
                SELECT o.id, COALESCE(o.service_area_id, b.service_area_id) AS service_area_id
                FROM offices AS o
                JOIN locations AS l ON l.id = o.location_id
                JOIN buildings AS b ON b.id = l.building_id
                WHERE o.id = ANY(:office_ids)
            """),
            {"office_ids": office_ids},
        ).mappings()
        if row["service_area_id"] is not None
    }


def find_unassigned_tickets(
    session: Session,
    day_start: datetime,
    day_end: datetime,
    area_ids: list[int] | None,
    brigade_ids: list[int] | None = None,
) -> list[RowMapping]:
    """Open tickets without an engineer whose visit window touches the day.

    `area_ids=None` means every area; an empty list means none is visible.
    """
    if area_ids is not None and not area_ids:
        return []
    scope = f"AND {TICKET_AREA_SQL} = ANY(:area_ids)" if area_ids is not None else ""
    brigade_scope = ""
    if brigade_ids is not None:
        if not brigade_ids:
            return []
        brigade_scope = f"""
            AND (
                t.brigade_id = ANY(:brigade_ids)
                OR (
                    t.brigade_id IS NULL
                    AND (
                        SELECT COUNT(*)
                        FROM brigades AS area_brigade
                        JOIN divisions AS area_division
                          ON area_division.id = area_brigade.division_id
                        WHERE area_division.service_area_id = {TICKET_AREA_SQL}
                    ) = 1
                    AND EXISTS (
                        SELECT 1
                        FROM brigades AS selected_brigade
                        JOIN divisions AS selected_division
                          ON selected_division.id = selected_brigade.division_id
                        WHERE selected_brigade.id = ANY(:brigade_ids)
                          AND selected_division.service_area_id = {TICKET_AREA_SQL}
                    )
                )
            )
        """
    return list(
        session.execute(
            text(f"""
                SELECT t.id, t.title, t.brigade_id, COALESCE(wt.name, t.work_type) AS work_type,
                       t.category, t.priority, t.visit_window_start, t.visit_window_end,
                       t.sla_deadline_at, {TICKET_AREA_SQL} AS service_area_id
                FROM tickets AS t
                JOIN locations AS ticket_location ON ticket_location.id = t.location_id
                JOIN buildings AS ticket_building
                    ON ticket_building.id = ticket_location.building_id
                LEFT JOIN work_types AS wt ON wt.id = t.work_type_id
                WHERE t.assigned_worker_id IS NULL
                  AND t.status = 'planned'
                  AND t.visit_window_start < :day_end
                  AND t.visit_window_end > :day_start
                  {scope}
                  {brigade_scope}
                ORDER BY t.priority, t.visit_window_start, t.id
            """),
            {
                "day_start": day_start,
                "day_end": day_end,
                "area_ids": area_ids or [],
                "brigade_ids": brigade_ids or [],
            },
        )
        .mappings()
        .all()
    )

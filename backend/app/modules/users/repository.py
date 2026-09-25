"""Literal, parameterized SQL for users, worker profiles, and skills."""

from sqlalchemy import RowMapping, text
from sqlalchemy.orm import Session

USER_SELECT_COLUMNS = """
    u.id, u.name, u.surname, u.lastname, u.username, u.password_hash, u.role,
    u.created_at, u.updated_at, u.archived_at,
    w.workshift_start, w.workshift_end, w.transport_type, w.is_on_line,
    w.service_area_id, w.start_location_id, w.stock_office_id, w.end_location_id,
    b.id AS brigade_id, b.name AS brigade_name,
    COALESCE(
        array_remove(array_agg(ws.skill ORDER BY ws.skill), NULL),
        ARRAY[]::varchar[]
    ) AS skills
"""

USER_SELECT_JOINS = """
    FROM users AS u
    LEFT JOIN workers AS w ON w.user_id = u.id
    LEFT JOIN brigade_members AS bm ON bm.worker_id = w.user_id
    LEFT JOIN brigades AS b ON b.id = bm.brigade_id
    LEFT JOIN worker_skill_assignments AS wsa ON wsa.worker_id = w.user_id
    LEFT JOIN worker_skills AS ws ON ws.id = wsa.skill_id
"""

USER_SELECT_GROUP_BY = """
    GROUP BY u.id, u.name, u.surname, u.lastname, u.username, u.password_hash, u.role,
             u.created_at, u.updated_at, u.archived_at, w.workshift_start, w.workshift_end,
             w.transport_type, w.is_on_line,
             w.service_area_id, w.start_location_id, w.stock_office_id, w.end_location_id,
             b.id, b.name
"""


def add_user(session: Session, values: dict[str, object]) -> int:
    return session.execute(
        text("""
            INSERT INTO users (name, surname, lastname, username, password_hash, role)
            VALUES (:name, :surname, :lastname, :username, :password_hash, :role)
            RETURNING id
        """),
        values,
    ).scalar_one()


def add_worker(session: Session, values: dict[str, object]) -> None:
    session.execute(
        text("""
            INSERT INTO workers (
                user_id, workshift_start, workshift_end, transport_type,
                service_area_id, start_location_id, stock_office_id, end_location_id
            )
            VALUES (
                :user_id, :workshift_start, :workshift_end, :transport_type,
                :service_area_id, :start_location_id, :stock_office_id, :end_location_id
            )
        """),
        {
            "transport_type": "walking",
            "service_area_id": None,
            "start_location_id": None,
            "stock_office_id": None,
            "end_location_id": None,
            **values,
        },
    )


def add_skill(session: Session, skill: str) -> int:
    return session.execute(
        text("""
            INSERT INTO worker_skills (skill)
            VALUES (:skill)
            RETURNING id
        """),
        {"skill": skill},
    ).scalar_one()


def find_skill_by_name(session: Session, skill: str) -> RowMapping | None:
    return (
        session.execute(
            text("""
                SELECT id, skill
                FROM worker_skills
                WHERE lower(skill) = lower(:skill)
            """),
            {"skill": skill},
        )
        .mappings()
        .one_or_none()
    )


def ensure_skill(session: Session, skill: str) -> int:
    return session.execute(
        text("""
            INSERT INTO worker_skills (skill)
            VALUES (:skill)
            ON CONFLICT (skill) DO UPDATE SET skill = EXCLUDED.skill
            RETURNING id
        """),
        {"skill": skill},
    ).scalar_one()


def assign_worker_skill(session: Session, worker_id: int, skill_id: int) -> None:
    session.execute(
        text("""
            INSERT INTO worker_skill_assignments (worker_id, skill_id)
            VALUES (:worker_id, :skill_id)
            ON CONFLICT DO NOTHING
        """),
        {"worker_id": worker_id, "skill_id": skill_id},
    )


def list_skills(session: Session) -> list[RowMapping]:
    return list(
        session.execute(
            text("""
                SELECT id, skill
                FROM worker_skills
                ORDER BY skill ASC
            """)
        )
        .mappings()
        .all()
    )


def find_user_by_username(session: Session, username: str) -> RowMapping | None:
    return (
        session.execute(
            text(f"""
                SELECT {USER_SELECT_COLUMNS}
                {USER_SELECT_JOINS}
                WHERE lower(u.username) = lower(:username)
                {USER_SELECT_GROUP_BY}
            """),
            {"username": username},
        )
        .mappings()
        .one_or_none()
    )


def find_user_by_id(
    session: Session,
    user_id: int,
    viewer_id: int | None = None,
    viewer_role: str | None = None,
) -> RowMapping | None:
    return (
        session.execute(
            text(f"""
                SELECT {USER_SELECT_COLUMNS}
                {USER_SELECT_JOINS}
                WHERE u.id = :user_id
                  AND (
                    CAST(:viewer_role AS TEXT) IS NULL
                    OR CAST(:viewer_role AS TEXT) <> 'foreman'
                    OR u.id = :viewer_id
                    OR EXISTS (
                        SELECT 1
                        FROM brigade_members AS visible_member
                        JOIN brigades AS visible_brigade
                          ON visible_brigade.id = visible_member.brigade_id
                        WHERE visible_member.worker_id = u.id
                          AND visible_brigade.foreman_id = :viewer_id
                    )
                  )
                {USER_SELECT_GROUP_BY}
            """),
            {"user_id": user_id, "viewer_id": viewer_id, "viewer_role": viewer_role},
        )
        .mappings()
        .one_or_none()
    )


def list_users(
    session: Session,
    role: str | None = None,
    brigade_id: int | None = None,
    viewer_id: int | None = None,
    viewer_role: str | None = None,
    include_archived: bool = False,
) -> list[RowMapping]:
    return list(
        session.execute(
            text(f"""
                SELECT {USER_SELECT_COLUMNS}
                {USER_SELECT_JOINS}
                WHERE (CAST(:role AS TEXT) IS NULL OR u.role = :role)
                  AND (:include_archived OR u.archived_at IS NULL)
                  AND (
                    CAST(:brigade_id AS integer) IS NULL
                    OR b.id = CAST(:brigade_id AS integer)
                    OR (
                        CAST(:viewer_role AS TEXT) = 'foreman'
                        AND u.id = :viewer_id
                        AND EXISTS (
                            SELECT 1
                            FROM brigades AS requested_brigade
                            WHERE requested_brigade.id = CAST(:brigade_id AS integer)
                              AND requested_brigade.foreman_id = :viewer_id
                        )
                    )
                  )
                  AND (
                    CAST(:viewer_role AS TEXT) IS NULL
                    OR CAST(:viewer_role AS TEXT) <> 'foreman'
                    OR u.id = :viewer_id
                    OR EXISTS (
                        SELECT 1
                        FROM brigade_members AS visible_member
                        JOIN brigades AS visible_brigade
                          ON visible_brigade.id = visible_member.brigade_id
                        WHERE visible_member.worker_id = u.id
                          AND visible_brigade.foreman_id = :viewer_id
                    )
                  )
                {USER_SELECT_GROUP_BY}
                ORDER BY u.id ASC
            """),
            {
                "role": role,
                "brigade_id": brigade_id,
                "viewer_id": viewer_id,
                "viewer_role": viewer_role,
                "include_archived": include_archived,
            },
        )
        .mappings()
        .all()
    )


def update_user(session: Session, user_id: int, values: dict[str, object]) -> None:
    if not values:
        return
    allowed_keys = {"name", "surname", "lastname", "username", "password_hash", "role"}
    filtered_values = {k: v for k, v in values.items() if k in allowed_keys}
    if not filtered_values:
        return
    assignments = ", ".join(f"{key} = :{key}" for key in filtered_values)
    session.execute(
        text(f"UPDATE users SET {assignments}, updated_at = now() WHERE id = :user_id"),
        {**filtered_values, "user_id": user_id},
    )


def upsert_worker(session: Session, user_id: int, values: dict[str, object]) -> None:
    session.execute(
        text("""
            INSERT INTO workers (
                user_id, workshift_start, workshift_end, transport_type,
                service_area_id, start_location_id, stock_office_id, end_location_id
            )
            VALUES (
                :user_id, :workshift_start, :workshift_end, :transport_type,
                :service_area_id, :start_location_id, :stock_office_id, :end_location_id
            )
            ON CONFLICT (user_id) DO UPDATE SET
                workshift_start = EXCLUDED.workshift_start,
                workshift_end = EXCLUDED.workshift_end,
                transport_type = EXCLUDED.transport_type,
                service_area_id = EXCLUDED.service_area_id,
                start_location_id = EXCLUDED.start_location_id,
                stock_office_id = EXCLUDED.stock_office_id,
                end_location_id = EXCLUDED.end_location_id
        """),
        {
            "user_id": user_id,
            "transport_type": "walking",
            "service_area_id": None,
            "start_location_id": None,
            "stock_office_id": None,
            "end_location_id": None,
            **values,
        },
    )


def lock_user(session: Session, user_id: int) -> RowMapping | None:
    return (
        session.execute(
            text("SELECT id, role, archived_at FROM users WHERE id = :user_id FOR UPDATE"),
            {"user_id": user_id},
        )
        .mappings()
        .one_or_none()
    )


def set_archived(session: Session, user_id: int, archived: bool) -> None:
    session.execute(
        text("""
            UPDATE users
            SET archived_at = CASE WHEN :archived THEN now() END, updated_at = now()
            WHERE id = :user_id
        """),
        {"user_id": user_id, "archived": archived},
    )


def find_active_work(session: Session, worker_id: int) -> dict[str, list]:
    """Work that would be orphaned if the engineer stopped receiving tickets now."""
    ticket_ids = (
        session.execute(
            text("""
                SELECT ticket.id
                FROM tickets AS ticket
                WHERE ticket.assigned_worker_id = :worker_id
                  AND ticket.status IN ('planned', 'in_progress')
                ORDER BY ticket.id
            """),
            {"worker_id": worker_id},
        )
        .scalars()
        .all()
    )
    equipment = (
        session.execute(
            text("""
                SELECT appliance_id, quantity
                FROM worker_appliances
                WHERE worker_id = :worker_id AND quantity > 0
                ORDER BY appliance_id
            """),
            {"worker_id": worker_id},
        )
        .mappings()
        .all()
    )
    return {"ticket_ids": list(ticket_ids), "equipment_on_hand": [dict(row) for row in equipment]}


def end_worker_duties(session: Session, user_id: int) -> None:
    """Current brigade membership and the worker-only calendar link end; history stays."""
    session.execute(
        text("DELETE FROM brigade_members WHERE worker_id = :user_id"), {"user_id": user_id}
    )
    session.execute(
        text("DELETE FROM calendar_tokens WHERE user_id = :user_id"), {"user_id": user_id}
    )


def delete_push_subscriptions(session: Session, user_id: int) -> None:
    session.execute(
        text("DELETE FROM push_subscriptions WHERE user_id = :user_id"), {"user_id": user_id}
    )


# Rows that only serve the live account; every other reference to a user is history.
DISPOSABLE_REFERENCES = (
    "brigade_members",
    "calendar_tokens",
    "notification_events",
    "push_subscriptions",
    "refresh_tokens",
    "worker_skill_assignments",
    "workers",
)


def find_history_links(session: Session, user_id: int) -> dict[str, int]:
    """Count rows of every table that references the user or the worker profile.

    Foreign keys are read from the catalog, so a history table added later is protected
    without changing this function: only DISPOSABLE_REFERENCES may be deleted with the user.
    """
    references = session.execute(
        text("""
            SELECT child.relname AS table_name, attribute.attname AS column_name
            FROM pg_constraint AS fk
            JOIN pg_class AS child ON child.oid = fk.conrelid
            JOIN pg_class AS parent ON parent.oid = fk.confrelid
            JOIN pg_attribute AS attribute
                ON attribute.attrelid = fk.conrelid AND attribute.attnum = fk.conkey[1]
            WHERE fk.contype = 'f'
              AND cardinality(fk.conkey) = 1
              AND parent.relnamespace = to_regnamespace(current_schema())
              AND parent.relname IN ('users', 'workers')
              AND child.relname <> ALL(:disposable)
            ORDER BY child.relname, attribute.attname
        """),
        {"disposable": list(DISPOSABLE_REFERENCES)},
    ).all()
    links: dict[str, int] = {}
    for table_name, column_name in references:
        table = '"' + table_name.replace('"', '""') + '"'
        column = '"' + column_name.replace('"', '""') + '"'
        count = session.execute(
            text(f"SELECT count(*) FROM {table} WHERE {column} = :user_id"), {"user_id": user_id}
        ).scalar_one()
        if count:
            links[table_name] = links.get(table_name, 0) + count
    return links


def clear_worker_skills(session: Session, worker_id: int) -> None:
    session.execute(
        text("DELETE FROM worker_skill_assignments WHERE worker_id = :worker_id"),
        {"worker_id": worker_id},
    )


def delete_user(session: Session, user_id: int) -> bool:
    result = session.execute(
        text("DELETE FROM users WHERE id = :user_id"),
        {"user_id": user_id},
    )
    return (result.rowcount or 0) > 0


def foreman_manages_brigade(session: Session, user_id: int) -> bool:
    return session.execute(
        text("SELECT EXISTS(SELECT 1 FROM brigades WHERE foreman_id = :user_id)"),
        {"user_id": user_id},
    ).scalar_one()


def lock_worker_line_status(session: Session, worker_id: int) -> RowMapping | None:
    return (
        session.execute(
            text("""
                SELECT w.user_id, w.is_on_line, w.workshift_start, w.workshift_end
                FROM workers AS w
                JOIN users AS u ON u.id = w.user_id
                WHERE w.user_id = :worker_id
                  AND u.role = 'worker'
                  AND u.archived_at IS NULL
                FOR UPDATE OF w
            """),
            {"worker_id": worker_id},
        )
        .mappings()
        .one_or_none()
    )


def update_worker_line_status(session: Session, worker_id: int, is_on_line: bool) -> None:
    session.execute(
        text("""
            UPDATE workers
            SET is_on_line = :is_on_line
            WHERE user_id = :worker_id
        """),
        {"worker_id": worker_id, "is_on_line": is_on_line},
    )


def release_planned_assignments(session: Session, worker_id: int) -> list[int]:
    return sorted(
        session.execute(
            text("""
                UPDATE tickets
                SET assigned_worker_id = NULL
                WHERE assigned_worker_id = :worker_id
                  AND status = 'planned'
                  AND lifecycle_state IN ('waiting_assignment', 'assigned')
                RETURNING id
            """),
            {"worker_id": worker_id},
        )
        .scalars()
        .all()
    )


def clear_planned_times_without_assignees(session: Session, ticket_ids: list[int]) -> None:
    if not ticket_ids:
        return
    session.execute(
        text("""
            UPDATE tickets AS ticket
            SET planned_start_at = NULL,
                planned_end_at = NULL,
                updated_at = now()
            WHERE ticket.id = ANY(:ticket_ids)
              AND ticket.status = 'planned'
              AND NOT EXISTS (
                  SELECT 1
                  WHERE ticket.assigned_worker_id IS NOT NULL
              )
        """),
        {"ticket_ids": ticket_ids},
    )


def list_worker_day_contexts(session: Session, worker_id: int) -> list[RowMapping]:
    return list(
        session.execute(
            text(
                """
                SELECT DISTINCT building.service_area_id,
                    COALESCE(
                        route.route_date,
                        (ticket.visit_window_start AT TIME ZONE 'Europe/Moscow')::date
                    )
                    AS route_date
                FROM tickets AS ticket
                JOIN locations AS location ON location.id = ticket.location_id
                JOIN buildings AS building ON building.id = location.building_id
                LEFT JOIN routes AS route
                    ON route.worker_id = ticket.assigned_worker_id
                   AND route.route_date =
                       (ticket.visit_window_start AT TIME ZONE 'Europe/Moscow')::date
                WHERE ticket.assigned_worker_id = :worker_id
                ORDER BY building.service_area_id, route_date
                """
            ),
            {"worker_id": worker_id},
        )
        .mappings()
        .all()
    )

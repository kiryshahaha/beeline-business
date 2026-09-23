"""Literal, parameterized SQL for users, worker profiles, and skills."""

from sqlalchemy import RowMapping, text
from sqlalchemy.orm import Session

USER_SELECT_COLUMNS = """
    u.id, u.name, u.surname, u.lastname, u.username, u.password_hash, u.role,
    u.created_at, u.updated_at,
    w.workshift_start, w.workshift_end, w.transport_type, w.is_on_line,
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
             u.created_at, u.updated_at, w.workshift_start, w.workshift_end,
             w.transport_type, w.is_on_line, b.id, b.name
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
            INSERT INTO workers (user_id, workshift_start, workshift_end, transport_type)
            VALUES (:user_id, :workshift_start, :workshift_end, :transport_type)
        """),
        {"transport_type": "walking", **values},
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
) -> list[RowMapping]:
    return list(
        session.execute(
            text(f"""
                SELECT {USER_SELECT_COLUMNS}
                {USER_SELECT_JOINS}
                WHERE (CAST(:role AS TEXT) IS NULL OR u.role = :role)
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
            INSERT INTO workers (user_id, workshift_start, workshift_end, transport_type)
            VALUES (:user_id, :workshift_start, :workshift_end, :transport_type)
            ON CONFLICT (user_id) DO UPDATE SET
                workshift_start = EXCLUDED.workshift_start,
                workshift_end = EXCLUDED.workshift_end,
                transport_type = EXCLUDED.transport_type
        """),
        {"user_id": user_id, **values},
    )


def delete_worker(session: Session, user_id: int) -> None:
    session.execute(
        text("DELETE FROM workers WHERE user_id = :user_id"),
        {"user_id": user_id},
    )


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
                SELECT user_id, is_on_line, workshift_start, workshift_end
                FROM workers
                WHERE user_id = :worker_id
                FOR UPDATE
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
                DELETE FROM ticket_assignments AS assignment
                USING tickets AS ticket
                WHERE assignment.ticket_id = ticket.id
                  AND assignment.worker_id = :worker_id
                  AND ticket.status = 'planned'
                  AND ticket.lifecycle_state IN ('waiting_assignment', 'assigned')
                RETURNING assignment.ticket_id
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
                  FROM ticket_assignments AS assignment
                  WHERE assignment.ticket_id = ticket.id
              )
        """),
        {"ticket_ids": ticket_ids},
    )


def list_worker_day_contexts(session: Session, worker_id: int) -> list[RowMapping]:
    return list(
        session.execute(
            text(
                """
                SELECT DISTINCT building.district_id,
                    COALESCE(
                        route.route_date,
                        (ticket.visit_window_start AT TIME ZONE 'Europe/Moscow')::date
                    )
                    AS route_date
                FROM ticket_assignments AS assignment
                JOIN tickets AS ticket ON ticket.id = assignment.ticket_id
                JOIN locations AS location ON location.id = ticket.location_id
                JOIN buildings AS building ON building.id = location.building_id
                LEFT JOIN routes AS route
                    ON route.worker_id = assignment.worker_id
                   AND route.route_date =
                       (ticket.visit_window_start AT TIME ZONE 'Europe/Moscow')::date
                WHERE assignment.worker_id = :worker_id
                ORDER BY building.district_id, route_date
                """
            ),
            {"worker_id": worker_id},
        )
        .mappings()
        .all()
    )

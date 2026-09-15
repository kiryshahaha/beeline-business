"""Literal, parameterized SQL for users, worker profiles, and skills."""

from sqlalchemy import RowMapping, text
from sqlalchemy.orm import Session


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
            INSERT INTO workers (user_id, workshift_start, workshift_end)
            VALUES (:user_id, :workshift_start, :workshift_end)
        """),
        values,
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
            text("""
                SELECT
                    u.id, u.name, u.surname, u.lastname, u.username, u.password_hash, u.role,
                    u.created_at, u.updated_at,
                    w.workshift_start, w.workshift_end,
                    COALESCE(
                        array_remove(array_agg(ws.skill ORDER BY ws.skill), NULL),
                        ARRAY[]::varchar[]
                    ) AS skills
                FROM users AS u
                LEFT JOIN workers AS w ON w.user_id = u.id
                LEFT JOIN worker_skill_assignments AS wsa ON wsa.worker_id = w.user_id
                LEFT JOIN worker_skills AS ws ON ws.id = wsa.skill_id
                WHERE lower(u.username) = lower(:username)
                GROUP BY u.id, u.name, u.surname, u.lastname, u.username, u.password_hash, u.role,
                         u.created_at, u.updated_at, w.workshift_start, w.workshift_end
            """),
            {"username": username},
        )
        .mappings()
        .one_or_none()
    )


def find_user_by_id(session: Session, user_id: int) -> RowMapping | None:
    return (
        session.execute(
            text("""
                SELECT
                    u.id, u.name, u.surname, u.lastname, u.username, u.password_hash, u.role,
                    u.created_at, u.updated_at,
                    w.workshift_start, w.workshift_end,
                    COALESCE(
                        array_remove(array_agg(ws.skill ORDER BY ws.skill), NULL),
                        ARRAY[]::varchar[]
                    ) AS skills
                FROM users AS u
                LEFT JOIN workers AS w ON w.user_id = u.id
                LEFT JOIN worker_skill_assignments AS wsa ON wsa.worker_id = w.user_id
                LEFT JOIN worker_skills AS ws ON ws.id = wsa.skill_id
                WHERE u.id = :user_id
                GROUP BY u.id, u.name, u.surname, u.lastname, u.username, u.password_hash, u.role,
                         u.created_at, u.updated_at, w.workshift_start, w.workshift_end
            """),
            {"user_id": user_id},
        )
        .mappings()
        .one_or_none()
    )


def list_users(session: Session, role: str | None = None) -> list[RowMapping]:
    return list(
        session.execute(
            text("""
                SELECT
                    u.id, u.name, u.surname, u.lastname, u.username, u.password_hash, u.role,
                    u.created_at, u.updated_at,
                    w.workshift_start, w.workshift_end,
                    COALESCE(
                        array_remove(array_agg(ws.skill ORDER BY ws.skill), NULL),
                        ARRAY[]::varchar[]
                    ) AS skills
                FROM users AS u
                LEFT JOIN workers AS w ON w.user_id = u.id
                LEFT JOIN worker_skill_assignments AS wsa ON wsa.worker_id = w.user_id
                LEFT JOIN worker_skills AS ws ON ws.id = wsa.skill_id
                WHERE (CAST(:role AS TEXT) IS NULL OR u.role = :role)
                GROUP BY u.id, u.name, u.surname, u.lastname, u.username, u.password_hash, u.role,
                         u.created_at, u.updated_at, w.workshift_start, w.workshift_end
                ORDER BY u.id ASC
            """),
            {"role": role},
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
            INSERT INTO workers (user_id, workshift_start, workshift_end)
            VALUES (:user_id, :workshift_start, :workshift_end)
            ON CONFLICT (user_id) DO UPDATE SET
                workshift_start = EXCLUDED.workshift_start,
                workshift_end = EXCLUDED.workshift_end
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

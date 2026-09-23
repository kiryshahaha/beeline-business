"""Parameterized SQL queries for brigades and active memberships."""

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

BRIGADE_COLUMNS = """
    b.id,
    b.name,
    b.foreman_id,
    b.office_id,
    b.division_id,
    b.created_at,
    b.updated_at,
    COALESCE(
        (
            SELECT array_agg(bm.worker_id ORDER BY bm.worker_id)
            FROM brigade_members AS bm
            WHERE bm.brigade_id = b.id
        ),
        ARRAY[]::integer[]
    ) AS worker_ids
"""


def find_brigade_by_id(session: Session, brigade_id: int) -> RowMapping | None:
    return (
        session.execute(
            text(f"SELECT {BRIGADE_COLUMNS} FROM brigades AS b WHERE b.id = :brigade_id"),
            {"brigade_id": brigade_id},
        )
        .mappings()
        .one_or_none()
    )


def lock_brigade_by_id(session: Session, brigade_id: int) -> RowMapping | None:
    return (
        session.execute(
            text(
                f"SELECT {BRIGADE_COLUMNS} FROM brigades AS b WHERE b.id = :brigade_id FOR UPDATE"
            ),
            {"brigade_id": brigade_id},
        )
        .mappings()
        .one_or_none()
    )


def find_brigade_by_name(session: Session, name: str) -> RowMapping | None:
    return (
        session.execute(
            text(f"SELECT {BRIGADE_COLUMNS} FROM brigades AS b WHERE lower(b.name) = lower(:name)"),
            {"name": name},
        )
        .mappings()
        .one_or_none()
    )


def find_brigade_by_foreman(session: Session, foreman_id: int) -> RowMapping | None:
    return (
        session.execute(
            text(f"SELECT {BRIGADE_COLUMNS} FROM brigades AS b WHERE b.foreman_id = :foreman_id"),
            {"foreman_id": foreman_id},
        )
        .mappings()
        .one_or_none()
    )


def list_visible_brigades(session: Session, viewer_id: int, viewer_role: str) -> list[RowMapping]:
    return list(
        session.execute(
            text(f"""
                SELECT {BRIGADE_COLUMNS}
                FROM brigades AS b
                WHERE :viewer_role = 'observer'
                   OR (:viewer_role = 'foreman' AND b.foreman_id = :viewer_id)
                   OR (
                        :viewer_role = 'worker'
                        AND EXISTS (
                            SELECT 1
                            FROM brigade_members AS bm
                            WHERE bm.brigade_id = b.id AND bm.worker_id = :viewer_id
                        )
                   )
                ORDER BY b.id ASC
            """),
            {"viewer_id": viewer_id, "viewer_role": viewer_role},
        )
        .mappings()
        .all()
    )


def find_visible_brigade(
    session: Session, brigade_id: int, viewer_id: int, viewer_role: str
) -> RowMapping | None:
    return (
        session.execute(
            text(f"""
                SELECT {BRIGADE_COLUMNS}
                FROM brigades AS b
                WHERE b.id = :brigade_id
                  AND (
                    :viewer_role = 'observer'
                    OR (:viewer_role = 'foreman' AND b.foreman_id = :viewer_id)
                    OR (
                        :viewer_role = 'worker'
                        AND EXISTS (
                            SELECT 1
                            FROM brigade_members AS bm
                            WHERE bm.brigade_id = b.id AND bm.worker_id = :viewer_id
                        )
                    )
                  )
            """),
            {
                "brigade_id": brigade_id,
                "viewer_id": viewer_id,
                "viewer_role": viewer_role,
            },
        )
        .mappings()
        .one_or_none()
    )


def lock_user_role(session: Session, user_id: int) -> str | None:
    """Keep the validated role stable until the brigade transaction completes."""
    return session.execute(
        text("SELECT role FROM users WHERE id = :user_id FOR UPDATE"), {"user_id": user_id}
    ).scalar_one_or_none()


def find_worker_ids(session: Session, worker_ids: list[int]) -> set[int]:
    if not worker_ids:
        return set()
    return set(
        session.execute(
            text("SELECT user_id FROM workers WHERE user_id = ANY(CAST(:worker_ids AS integer[]))"),
            {"worker_ids": worker_ids},
        ).scalars()
    )


def find_occupied_worker_ids(
    session: Session, worker_ids: list[int], excluded_brigade_id: int | None = None
) -> set[int]:
    if not worker_ids:
        return set()
    return set(
        session.execute(
            text("""
                SELECT worker_id
                FROM brigade_members
                WHERE worker_id = ANY(CAST(:worker_ids AS integer[]))
                  AND (
                    CAST(:excluded_brigade_id AS integer) IS NULL
                    OR brigade_id <> CAST(:excluded_brigade_id AS integer)
                  )
            """),
            {"worker_ids": worker_ids, "excluded_brigade_id": excluded_brigade_id},
        ).scalars()
    )


def add_brigade(session: Session, name: str, foreman_id: int, office_id: int) -> int:
    return session.execute(
        text("""
            INSERT INTO brigades (name, foreman_id, office_id)
            VALUES (:name, :foreman_id, :office_id)
            RETURNING id
        """),
        {"name": name, "foreman_id": foreman_id, "office_id": office_id},
    ).scalar_one()


def update_brigade_foreman_and_office(
    session: Session, brigade_id: int, foreman_id: int, office_id: int
) -> None:
    session.execute(
        text("""
            UPDATE brigades
            SET foreman_id = :foreman_id, office_id = :office_id, updated_at = now()
            WHERE id = :brigade_id
        """),
        {"brigade_id": brigade_id, "foreman_id": foreman_id, "office_id": office_id},
    )


def delete_brigade_members(session: Session, brigade_id: int) -> None:
    session.execute(
        text("DELETE FROM brigade_members WHERE brigade_id = :brigade_id"),
        {"brigade_id": brigade_id},
    )


def add_brigade_members(session: Session, brigade_id: int, worker_ids: list[int]) -> None:
    if not worker_ids:
        return
    session.execute(
        text("""
            INSERT INTO brigade_members (brigade_id, worker_id)
            VALUES (:brigade_id, :worker_id)
        """),
        [{"brigade_id": brigade_id, "worker_id": worker_id} for worker_id in worker_ids],
    )

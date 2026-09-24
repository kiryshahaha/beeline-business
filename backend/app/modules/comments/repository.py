"""Literal, parameterized SQL for ticket comments."""

from sqlalchemy import RowMapping, text
from sqlalchemy.orm import Session

from app.modules.tickets import repository as tickets_repository


def ticket_exists(session: Session, ticket_id: int, *, foreman_id: int | None = None) -> bool:
    return tickets_repository.ticket_exists(session, ticket_id, foreman_id=foreman_id)


def is_worker_assigned(session: Session, ticket_id: int, worker_id: int) -> bool:
    return (
        session.execute(
            text("""
                SELECT EXISTS (
                    SELECT 1 FROM tickets
                        WHERE id = :ticket_id AND assigned_worker_id = :worker_id
                )
            """),
            {"ticket_id": ticket_id, "worker_id": worker_id},
        ).scalar_one()
        is True
    )


def add_comment(session: Session, ticket_id: int, author_id: int, value: str) -> int:
    return session.execute(
        text("""
            INSERT INTO ticket_comments (ticket_id, author_id, text)
            VALUES (:ticket_id, :author_id, :text)
            RETURNING id
        """),
        {"ticket_id": ticket_id, "author_id": author_id, "text": value},
    ).scalar_one()


COMMENT_SELECT_SQL = """
    SELECT
        tc.id, tc.ticket_id, tc.text, tc.created_at, tc.updated_at,
        u.id AS author_id, u.name AS author_name, u.surname AS author_surname,
        u.lastname AS author_lastname, u.username AS author_username, u.role AS author_role
    FROM ticket_comments AS tc
    JOIN users AS u ON u.id = tc.author_id
"""


def find_comment(session: Session, comment_id: int) -> RowMapping:
    return (
        session.execute(
            text(COMMENT_SELECT_SQL + " WHERE tc.id = :comment_id"),
            {"comment_id": comment_id},
        )
        .mappings()
        .one()
    )


def lock_comment(session: Session, ticket_id: int, comment_id: int) -> RowMapping | None:
    return (
        session.execute(
            text("""
                SELECT id, author_id FROM ticket_comments
                WHERE id = :comment_id AND ticket_id = :ticket_id
                FOR UPDATE
            """),
            {"comment_id": comment_id, "ticket_id": ticket_id},
        )
        .mappings()
        .one_or_none()
    )


def update_comment_text(session: Session, comment_id: int, value: str) -> None:
    session.execute(
        text("""
            UPDATE ticket_comments
            SET text = :text, updated_at = clock_timestamp()
            WHERE id = :comment_id
        """),
        {"comment_id": comment_id, "text": value},
    )


def list_comments(session: Session, ticket_id: int) -> list[RowMapping]:
    return list(
        session.execute(
            text(COMMENT_SELECT_SQL + " WHERE tc.ticket_id = :ticket_id ORDER BY tc.id ASC"),
            {"ticket_id": ticket_id},
        )
        .mappings()
        .all()
    )

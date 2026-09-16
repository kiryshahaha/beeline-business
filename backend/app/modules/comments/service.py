"""Ticket comment rules without HTTP-specific exceptions."""

from sqlalchemy import RowMapping
from sqlalchemy.orm import Session

from app.modules.comments import repository
from app.modules.comments.schemas import (
    CommentAuthorRead,
    CommentCreate,
    CommentRead,
    CommentUpdate,
)
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead


class TicketNotFoundError(Exception):
    pass


class PermissionDeniedError(Exception):
    pass


class CommentNotFoundError(Exception):
    pass


def _check_access(session: Session, ticket_id: int, user: UserRead) -> None:
    if not repository.ticket_exists(session, ticket_id):
        raise TicketNotFoundError
    if user.role == UserRole.WORKER and not repository.is_worker_assigned(
        session, ticket_id, user.id
    ):
        raise PermissionDeniedError


def _comment_from_row(row: RowMapping) -> CommentRead:
    return CommentRead(
        id=row["id"],
        ticket_id=row["ticket_id"],
        text=row["text"],
        created_at=row["created_at"],
        author=CommentAuthorRead(
            id=row["author_id"],
            name=row["author_name"],
            surname=row["author_surname"],
            lastname=row["author_lastname"],
            username=row["author_username"],
            role=UserRole(row["author_role"]),
        ),
    )


def create_comment(
    session: Session,
    ticket_id: int,
    user: UserRead,
    data: CommentCreate,
) -> CommentRead:
    with session.begin():
        _check_access(session, ticket_id, user)
        comment_id = repository.add_comment(session, ticket_id, user.id, data.text)
        return _comment_from_row(repository.find_comment(session, comment_id))


def update_comment(
    session: Session,
    ticket_id: int,
    comment_id: int,
    user: UserRead,
    data: CommentUpdate,
) -> CommentRead:
    with session.begin():
        _check_access(session, ticket_id, user)
        comment = repository.lock_comment(session, ticket_id, comment_id)
        if comment is None:
            raise CommentNotFoundError
        if comment["author_id"] != user.id:
            raise PermissionDeniedError
        repository.update_comment_text(session, comment_id, data.text)
        return _comment_from_row(repository.find_comment(session, comment_id))


def list_comments(session: Session, ticket_id: int, user: UserRead) -> list[CommentRead]:
    _check_access(session, ticket_id, user)
    return [_comment_from_row(row) for row in repository.list_comments(session, ticket_id)]

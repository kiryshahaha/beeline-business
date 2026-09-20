"""Issue, revoke and resolve calendar links without HTTP-specific exceptions."""

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.security import hash_token
from app.modules.calendar_feed import ics, repository
from app.modules.calendar_feed.schemas import CalendarLinkStatus

# Past tickets stay visible for a month so a worker can look back at recent visits.
FEED_HISTORY = timedelta(days=30)


class CalendarNotFoundError(Exception):
    pass


def issue_token(session: Session, user_id: int) -> tuple[str, datetime]:
    """Return a new plain token once; the database keeps only its SHA-256 hash."""
    token = secrets.token_urlsafe(32)
    with session.begin():
        created_at = repository.save_token(session, user_id, hash_token(token))
    return token, created_at


def get_status(session: Session, user_id: int) -> CalendarLinkStatus:
    with session.begin():
        created_at = repository.find_token_created_at(session, user_id)
    return CalendarLinkStatus(active=created_at is not None, created_at=created_at)


def revoke_token(session: Session, user_id: int) -> None:
    with session.begin():
        repository.delete_token(session, user_id)


def render_feed(session: Session, token: str, *, frontend_url: str | None) -> bytes:
    with session.begin():
        owner = repository.find_feed_owner(session, hash_token(token))
        if owner is None:
            raise CalendarNotFoundError
        tickets = repository.find_feed_tickets(
            session, owner["id"], datetime.now(UTC) - FEED_HISTORY
        )
    return ics.build_calendar(
        f"{owner['surname']} {owner['name']}", tickets, frontend_url=frontend_url
    )

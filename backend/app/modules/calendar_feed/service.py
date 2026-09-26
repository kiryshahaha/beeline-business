"""Issue, revoke and resolve calendar links without HTTP-specific exceptions."""

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.security import hash_token
from app.modules.calendar_feed import ics, repository
from app.modules.calendar_feed.schemas import CalendarLinkStatus

# Past tickets stay visible for a month so a worker can look back at recent visits.
FEED_HISTORY = timedelta(days=30)
# Assignments further ahead are not published: a plan that far out still changes.
FEED_HORIZON = timedelta(days=60)
# A ticket taken away from the worker is published as cancelled for this long.
RELEASE_GRACE = timedelta(days=14)


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


def render_feed(
    session: Session, token: str, *, frontend_url: str | None, now: datetime | None = None
) -> bytes:
    """The worker's current visits for a read-only calendar subscription.

    A calendar client polls the file on its own schedule, so a change reaches it only at
    the next refresh; the feed is an extra channel, not the source of truth.
    """
    now = now or datetime.now(UTC)
    with session.begin():
        owner = repository.find_feed_owner(session, hash_token(token))
        if owner is None:
            raise CalendarNotFoundError
        tickets, truncated = repository.find_feed_tickets(
            session,
            owner["id"],
            now=now,
            since=now - FEED_HISTORY,
            until=now + FEED_HORIZON,
        )
        released = repository.find_released_tickets(session, owner["id"], now - RELEASE_GRACE)
    return ics.build_calendar(
        f"{owner['surname']} {owner['name']}",
        tickets,
        frontend_url=frontend_url,
        now=now,
        released=released,
        truncated=truncated,
    )

"""Notification history and push subscription rules."""

from sqlalchemy.orm import Session

from app.modules.notifications import repository
from app.modules.notifications.schemas import NotificationRead, PushSubscriptionRead


class SubscriptionNotFoundError(Exception):
    pass


def register_subscription(session: Session, user_id: int, token: str) -> PushSubscriptionRead:
    with session.begin():
        row = repository.upsert_subscription(session, user_id, token)
        return PushSubscriptionRead.model_validate(dict(row))


def unregister_subscription(session: Session, user_id: int, token: str) -> None:
    with session.begin():
        if not repository.delete_subscription(session, user_id, token):
            raise SubscriptionNotFoundError


def list_notifications(
    session: Session,
    user_id: int,
    *,
    limit: int,
    offset: int,
    after_id: int | None = None,
) -> list[NotificationRead]:
    if after_id is not None:
        rows = repository.list_events_after(session, user_id, after_id, limit=limit)
    else:
        rows = repository.list_events(session, user_id, limit=limit, offset=offset)
    return [NotificationRead.model_validate(dict(row)) for row in rows]


def events_after(session: Session, user_id: int, after_id: int, *, limit: int) -> list:
    with session.begin_nested() if session.in_transaction() else session.begin():
        return list(repository.list_events_after(session, user_id, after_id, limit=limit))


def live_payload(event) -> dict:
    """The same message shape the dispatcher sends live, so the client handles one form."""
    return NotificationRead.model_validate(dict(event)).model_dump(mode="json")

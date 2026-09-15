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
) -> list[NotificationRead]:
    rows = repository.list_events(session, user_id, limit=limit, offset=offset)
    return [NotificationRead.model_validate(dict(row)) for row in rows]

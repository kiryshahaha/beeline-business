"""Deliver durable notification events through WebSocket and Firebase."""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.session import get_engine
from app.modules.notifications import repository
from app.modules.notifications.connections import connection_manager as default_connection_manager
from app.modules.notifications.enums import NotificationKind
from app.modules.notifications.firebase import create_push_gateway

logger = logging.getLogger(__name__)


def _event_payload(event) -> dict:
    kind = NotificationKind(event["kind"])
    return {
        "id": event["id"],
        "recipient_id": event["recipient_id"],
        "ticket_id": event["ticket_id"],
        "kind": kind.value,
        "data": event["data"],
        "created_at": event["created_at"].isoformat(),
    }


def _push_content(event) -> tuple[str, str, dict[str, str]]:
    kind = NotificationKind(event["kind"])
    ticket_title = event["data"].get("title", f"Заявка №{event['ticket_id']}")
    if kind == NotificationKind.TICKET_ASSIGNED:
        push_title = "Новая заявка"
        body = f"Вам назначена заявка «{ticket_title}»"
    else:
        push_title = "Статус заявки изменён"
        body = f"«{ticket_title}»: {event['data'].get('status', '')}"
    data = {
        "event_id": str(event["id"]),
        "kind": kind.value,
        "ticket_id": str(event["ticket_id"]),
    }
    for key, value in event["data"].items():
        data[key] = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return push_title, body, data


class NotificationDispatcher:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        connection_manager,
        push_gateway,
        batch_size: int = 100,
    ) -> None:
        self._session_factory = session_factory
        self._connections = connection_manager
        self._push = push_gateway
        self._batch_size = batch_size

    async def dispatch_once(self) -> int:
        with self._session_factory() as session, session.begin():
            events = repository.claim_pending_events(session, self._batch_size)

        for event in events:
            if event["websocket_delivered_at"] is None:
                await self._connections.publish(event["recipient_id"], _event_payload(event))
                with self._session_factory() as session, session.begin():
                    repository.mark_websocket_delivered(session, event["id"])

            if event["push_delivered_at"] is not None:
                continue
            with self._session_factory() as session:
                tokens = repository.list_subscription_tokens(session, event["recipient_id"])
            if not tokens or not self._push.enabled:
                with self._session_factory() as session, session.begin():
                    repository.mark_push_delivered(session, event["id"])
                continue

            title, body, data = _push_content(event)
            try:
                result = await asyncio.to_thread(
                    self._push.send,
                    tokens,
                    title=title,
                    body=body,
                    data=data,
                )
            except Exception as error:
                delay = min(300, 2 ** event["attempt_count"])
                with self._session_factory() as session, session.begin():
                    repository.record_push_failure(
                        session,
                        event["id"],
                        next_attempt_at=datetime.now(UTC) + timedelta(seconds=delay),
                        error=str(error),
                    )
                continue

            with self._session_factory() as session, session.begin():
                repository.delete_subscription_tokens(session, result.invalid_tokens)
                repository.mark_push_delivered(session, event["id"])
        return len(events)

    async def run(self, poll_interval_seconds: float) -> None:
        while True:
            try:
                await self.dispatch_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Notification delivery cycle failed")
            await asyncio.sleep(poll_interval_seconds)


def create_dispatcher() -> NotificationDispatcher:
    settings = get_settings()
    return NotificationDispatcher(
        sessionmaker(bind=get_engine()),
        connection_manager=default_connection_manager,
        push_gateway=create_push_gateway(settings),
    )

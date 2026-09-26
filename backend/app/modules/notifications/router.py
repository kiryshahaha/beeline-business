"""Notification history, push subscription, and WebSocket endpoints."""

from typing import Annotated

import jwt
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.session import get_session
from app.modules.auth.dependencies import get_current_user
from app.modules.notifications import service
from app.modules.notifications.connections import connection_manager
from app.modules.notifications.schemas import (
    NotificationRead,
    PushSubscriptionCreate,
    PushSubscriptionDelete,
    PushSubscriptionRead,
)
from app.modules.notifications.topology import delivery_state
from app.modules.users import service as users_service
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])
# Events replayed on reconnect before the client is told to page the rest over HTTP.
REPLAY_LIMIT = 200
DatabaseSession = Annotated[Session, Depends(get_session)]
CurrentUser = Annotated[UserRead, Depends(get_current_user)]


@router.get("", response_model=list[NotificationRead])
def list_notifications(
    session: DatabaseSession,
    current_user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=2_147_483_647)] = 0,
    after_id: Annotated[
        int | None,
        Query(
            ge=0,
            le=2_147_483_647,
            description="Вернуть события новее этого id по возрастанию — для догонки после "
            "переподключения без пропусков. offset при этом не используется.",
        ),
    ] = None,
) -> list[NotificationRead]:
    """История событий пользователя: новые сверху или, с after_id, по порядку после id."""
    return service.list_notifications(
        session, current_user.id, limit=limit, offset=offset, after_id=after_id
    )


@router.post("/push-subscriptions", response_model=PushSubscriptionRead, status_code=201)
def register_push_subscription(
    data: PushSubscriptionCreate,
    session: DatabaseSession,
    current_user: CurrentUser,
) -> PushSubscriptionRead:
    """Associate a browser's Firebase registration token with the current user."""
    return service.register_subscription(session, current_user.id, data.token)


@router.delete("/push-subscriptions", status_code=204)
def unregister_push_subscription(
    data: PushSubscriptionDelete,
    session: DatabaseSession,
    current_user: CurrentUser,
) -> Response:
    """Remove a Firebase token only when it belongs to the current user."""
    try:
        service.unregister_subscription(session, current_user.id, data.token)
    except service.SubscriptionNotFoundError as error:
        raise HTTPException(status_code=404, detail="Firebase-токен не найден") from error
    return Response(status_code=204)


def _authenticate_websocket(payload: object, session: Session) -> UserRead:
    if not isinstance(payload, dict) or payload.get("type") != "authenticate":
        raise ValueError("Expected authentication message")
    token = payload.get("token")
    if not isinstance(token, str):
        raise ValueError("Expected access token")
    decoded = decode_token(token)
    if decoded.get("type") != "access":
        raise ValueError("Expected access token")
    return users_service.get_user(session, int(decoded["sub"]))


def _last_event_id(payload: dict) -> int | None:
    value = payload.get("last_event_id")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2_147_483_647:
        raise ValueError("last_event_id must be a non-negative integer")
    return value


async def _replay(session: Session, websocket: WebSocket, user_id: int, after_id: int) -> None:
    """Send what the client missed since its last seen id, oldest first.

    The socket is registered before this runs, so an event created meanwhile arrives
    live or here; the connection manager sends each id to a socket once.
    """
    events = service.events_after(session, user_id, after_id, limit=REPLAY_LIMIT + 1)
    for event in events[:REPLAY_LIMIT]:
        await connection_manager.send(user_id, websocket, service.live_payload(event))
    if len(events) > REPLAY_LIMIT:
        await websocket.send_json(
            {"type": "replay_truncated", "next_after_id": events[REPLAY_LIMIT - 1]["id"]}
        )


@router.websocket("/ws")
async def notifications_websocket(
    websocket: WebSocket,
    session: DatabaseSession,
) -> None:
    """Authenticate with the first frame, then stream recipient-specific events."""
    await websocket.accept()
    try:
        payload = await websocket.receive_json()
        user = _authenticate_websocket(payload, session)
        last_event_id = _last_event_id(payload)
    except (jwt.PyJWTError, KeyError, TypeError, ValueError, users_service.UserNotFoundError):
        await websocket.close(code=1008, reason="Недействительный токен авторизации")
        return
    if not delivery_state.accepts_live_sockets():
        # Another process delivers live events; a socket here would silently get none.
        await websocket.close(code=1013, reason="Уведомления обслуживает другой процесс")
        return

    await connection_manager.connect(user.id, websocket)
    try:
        await websocket.send_json({"type": "authenticated", "user_id": user.id})
        if last_event_id is not None:
            await _replay(session, websocket, user.id, last_event_id)
        while True:
            message = await websocket.receive_json()
            if isinstance(message, dict) and message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        await connection_manager.disconnect(user.id, websocket)

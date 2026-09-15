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
from app.modules.users import service as users_service
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])
DatabaseSession = Annotated[Session, Depends(get_session)]
CurrentUser = Annotated[UserRead, Depends(get_current_user)]


@router.get("", response_model=list[NotificationRead])
def list_notifications(
    session: DatabaseSession,
    current_user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=2_147_483_647)] = 0,
) -> list[NotificationRead]:
    """Return the current user's durable event history, newest first."""
    return service.list_notifications(session, current_user.id, limit=limit, offset=offset)


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
    except (jwt.PyJWTError, KeyError, TypeError, ValueError, users_service.UserNotFoundError):
        await websocket.close(code=1008, reason="Недействительный токен авторизации")
        return

    await connection_manager.connect(user.id, websocket)
    try:
        await websocket.send_json({"type": "authenticated", "user_id": user.id})
        while True:
            message = await websocket.receive_json()
            if isinstance(message, dict) and message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        await connection_manager.disconnect(user.id, websocket)

"""Calendar subscription: a worker issues a secret link, calendar apps download the feed.

Google and Apple Calendar cannot send Authorization headers, so the feed is authorized
by the secret token in the URL. Treat the link like a password.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_session
from app.modules.auth.dependencies import require_roles
from app.modules.calendar_feed import service
from app.modules.calendar_feed.schemas import CalendarLinkRead, CalendarLinkStatus
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/api/v1/schedule", tags=["calendar"])
DatabaseSession = Annotated[Session, Depends(get_session)]
CurrentWorker = Annotated[UserRead, Depends(require_roles(UserRole.WORKER))]


def _feed_url(request: Request, token: str) -> str:
    # Behind a proxy request.base_url may be internal; PUBLIC_API_URL fixes the public host.
    base_url = get_settings().public_api_url or str(request.base_url)
    return f"{base_url.rstrip('/')}/api/v1/schedule/calendar.ics?token={token}"


@router.post(
    "/calendar/token", response_model=CalendarLinkRead, status_code=status.HTTP_201_CREATED
)
def issue_calendar_link(
    request: Request, session: DatabaseSession, current_user: CurrentWorker
) -> CalendarLinkRead:
    """Выпустить личную ссылку на календарь заявок. Предыдущая ссылка перестаёт работать."""
    token, created_at = service.issue_token(session, current_user.id)
    return CalendarLinkRead(url=_feed_url(request, token), created_at=created_at)


@router.get("/calendar/token", response_model=CalendarLinkStatus)
def get_calendar_link_status(
    session: DatabaseSession, current_user: CurrentWorker
) -> CalendarLinkStatus:
    """Проверить, выпущена ли ссылка. Сам токен не возвращается: хранится только его хеш."""
    return service.get_status(session, current_user.id)


@router.delete("/calendar/token", status_code=status.HTTP_204_NO_CONTENT)
def revoke_calendar_link(session: DatabaseSession, current_user: CurrentWorker) -> Response:
    """Отозвать ссылку: календари перестанут получать обновления."""
    service.revoke_token(session, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/calendar.ics",
    response_class=Response,
    responses={
        200: {"content": {"text/calendar": {}}, "description": "Файл iCalendar"},
        404: {"description": "Ссылка недействительна или отозвана"},
    },
)
def get_calendar_feed(
    session: DatabaseSession,
    token: Annotated[
        str, Query(min_length=1, max_length=200, description="Секрет из личной ссылки.")
    ],
) -> Response:
    """Файл .ics с заявками исполнителя для подписки в календаре. Авторизация — токен в URL."""
    try:
        content = service.render_feed(
            session, token, frontend_url=get_settings().frontend_url or None
        )
    except service.CalendarNotFoundError as error:
        raise HTTPException(status_code=404, detail="Календарь не найден") from error
    return Response(
        content=content,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'inline; filename="schedule.ics"',
            "Cache-Control": "private, no-store",
        },
    )

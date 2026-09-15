"""Authenticated ticket comment endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.auth.dependencies import get_current_user
from app.modules.comments import service
from app.modules.comments.schemas import CommentCreate, CommentRead
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/api/v1/tickets", tags=["ticket comments"])
DatabaseSession = Annotated[Session, Depends(get_session)]
CurrentUser = Annotated[UserRead, Depends(get_current_user)]
TicketId = Annotated[int, Path(ge=1, le=2_147_483_647)]


def _raise_http_error(error: Exception) -> None:
    if isinstance(error, service.TicketNotFoundError):
        raise HTTPException(status_code=404, detail="Заявка не найдена") from error
    raise HTTPException(status_code=403, detail="Нет доступа к комментариям заявки") from error


@router.get("/{id}/comments", response_model=list[CommentRead])
def list_ticket_comments(
    id: TicketId,
    session: DatabaseSession,
    current_user: CurrentUser,
) -> list[CommentRead]:
    """Return the ticket comment feed in creation order."""
    try:
        return service.list_comments(session, id, current_user)
    except (service.TicketNotFoundError, service.PermissionDeniedError) as error:
        _raise_http_error(error)


@router.post("/{id}/comments", response_model=CommentRead, status_code=status.HTTP_201_CREATED)
def create_ticket_comment(
    id: TicketId,
    data: CommentCreate,
    session: DatabaseSession,
    current_user: CurrentUser,
) -> CommentRead:
    """Add an authored note to a ticket."""
    try:
        return service.create_comment(session, id, current_user, data)
    except (service.TicketNotFoundError, service.PermissionDeniedError) as error:
        _raise_http_error(error)

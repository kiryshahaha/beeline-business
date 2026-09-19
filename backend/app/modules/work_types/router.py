"""Read-only work type reference; rows come from migrations."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.auth.dependencies import get_current_user
from app.modules.users.schemas import UserRead
from app.modules.work_types import service
from app.modules.work_types.schemas import WorkTypeRead

router = APIRouter(prefix="/api/v1/work-types", tags=["work-types"])
DatabaseSession = Annotated[Session, Depends(get_session)]
CurrentUser = Annotated[UserRead, Depends(get_current_user)]


@router.get("", response_model=list[WorkTypeRead])
def list_work_types(session: DatabaseSession, _: CurrentUser) -> list[WorkTypeRead]:
    """Получить справочник видов работ с нормативами по возрастанию ID.

    Доступно всем авторизованным пользователям.
    """
    return service.list_work_types(session)


@router.get(
    "/{id}", response_model=WorkTypeRead, responses={404: {"description": "Вид работ не найден"}}
)
def get_work_type(
    id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    session: DatabaseSession,
    _: CurrentUser,
) -> WorkTypeRead:
    """Получить один вид работ с разбивкой норматива."""
    try:
        return service.get_work_type(session, id)
    except service.WorkTypeNotFoundError as error:
        raise HTTPException(status_code=404, detail="Вид работ не найден") from error

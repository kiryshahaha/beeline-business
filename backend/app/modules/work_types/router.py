"""Work type reference: every signed-in user reads it, the observer creates and edits it."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.auth.dependencies import get_current_user, require_roles
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead
from app.modules.work_types import service
from app.modules.work_types.schemas import WorkTypeCreate, WorkTypeRead, WorkTypeUpdate

router = APIRouter(prefix="/api/v1/work-types", tags=["work-types"])
DatabaseSession = Annotated[Session, Depends(get_session)]
CurrentUser = Annotated[UserRead, Depends(get_current_user)]
CurrentObserver = Annotated[UserRead, Depends(require_roles(UserRole.OBSERVER))]
WorkTypeId = Annotated[int, Path(ge=1, le=2_147_483_647)]

NAME_CONFLICT_DETAIL = "Вид работ с таким названием уже существует"


@router.get("", response_model=list[WorkTypeRead])
def list_work_types(session: DatabaseSession, _: CurrentUser) -> list[WorkTypeRead]:
    """Получить справочник видов работ с нормативами по возрастанию ID.

    Доступно всем авторизованным пользователям.
    """
    return service.list_work_types(session)


@router.post(
    "",
    response_model=WorkTypeRead,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"description": NAME_CONFLICT_DETAIL}},
)
def create_work_type(
    data: WorkTypeCreate, session: DatabaseSession, response: Response, _: CurrentObserver
) -> WorkTypeRead:
    """Добавить вид работ с нормативом. Доступно только роли observer.

    norm_minutes не передаётся: PostgreSQL считает его как сумму трёх частей.
    """
    try:
        work_type = service.create_work_type(session, data)
    except service.WorkTypeNameAlreadyExistsError as error:
        raise HTTPException(status_code=409, detail=NAME_CONFLICT_DETAIL) from error
    response.headers["Location"] = f"/api/v1/work-types/{work_type.id}"
    return work_type


@router.get(
    "/{id}", response_model=WorkTypeRead, responses={404: {"description": "Вид работ не найден"}}
)
def get_work_type(id: WorkTypeId, session: DatabaseSession, _: CurrentUser) -> WorkTypeRead:
    """Получить один вид работ с разбивкой норматива."""
    try:
        return service.get_work_type(session, id)
    except service.WorkTypeNotFoundError as error:
        raise HTTPException(status_code=404, detail="Вид работ не найден") from error


@router.patch(
    "/{id}",
    response_model=WorkTypeRead,
    responses={
        404: {"description": "Вид работ не найден"},
        409: {"description": NAME_CONFLICT_DETAIL},
    },
)
def update_work_type(
    id: WorkTypeId, data: WorkTypeUpdate, session: DatabaseSession, _: CurrentObserver
) -> WorkTypeRead:
    """Изменить название или части норматива. Доступно только роли observer.

    Меняются только переданные поля; итоговый норматив пересчитывает PostgreSQL.
    """
    try:
        return service.update_work_type(session, id, data)
    except service.WorkTypeNotFoundError as error:
        raise HTTPException(status_code=404, detail="Вид работ не найден") from error
    except service.WorkTypeNameAlreadyExistsError as error:
        raise HTTPException(status_code=409, detail=NAME_CONFLICT_DETAIL) from error
    except service.WorkTypeNormNotPositiveError as error:
        raise HTTPException(status_code=422, detail="Норматив должен быть больше нуля") from error

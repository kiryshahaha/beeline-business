"""HTTP API for observer-managed brigades and scoped brigade reads."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.auth.dependencies import get_current_user, require_roles
from app.modules.brigades import service
from app.modules.brigades.schemas import BrigadeCreate, BrigadeMembersUpdate, BrigadeRead
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/api/v1/brigades", tags=["brigades"])
DatabaseSession = Annotated[Session, Depends(get_session)]
CurrentUser = Annotated[UserRead, Depends(get_current_user)]
CurrentObserver = Annotated[UserRead, Depends(require_roles(UserRole.OBSERVER))]


@router.post("", response_model=BrigadeRead, status_code=status.HTTP_201_CREATED)
def create_brigade(
    data: BrigadeCreate,
    session: DatabaseSession,
    response: Response,
    _: CurrentObserver,
) -> BrigadeRead:
    try:
        brigade = service.create_brigade(session, data)
    except service.BrigadeNameAlreadyExistsError as error:
        raise HTTPException(
            status_code=409, detail="Бригада с таким названием уже существует"
        ) from error
    except service.ForemanAlreadyAssignedError as error:
        raise HTTPException(
            status_code=409, detail="Бригадир уже руководит другой бригадой"
        ) from error
    except service.WorkerAlreadyAssignedError as error:
        raise HTTPException(
            status_code=409, detail="Исполнитель уже состоит в другой бригаде"
        ) from error
    except service.BrigadeConflictError as error:
        raise HTTPException(
            status_code=409, detail="Конфликт состава или руководителя бригады"
        ) from error
    except (service.ForemanInvalidError, service.WorkerNotFoundError) as error:
        raise HTTPException(
            status_code=422, detail="Указаны недопустимые бригадир или исполнители"
        ) from error
    response.headers["Location"] = f"/api/v1/brigades/{brigade.id}"
    return brigade


@router.get("", response_model=list[BrigadeRead])
def list_brigades(session: DatabaseSession, current_user: CurrentUser) -> list[BrigadeRead]:
    return service.list_brigades(session, current_user)


@router.get(
    "/{id}", response_model=BrigadeRead, responses={404: {"description": "Бригада не найдена"}}
)
def get_brigade(
    id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    session: DatabaseSession,
    current_user: CurrentUser,
) -> BrigadeRead:
    try:
        return service.get_brigade(session, id, current_user)
    except service.BrigadeNotFoundError as error:
        raise HTTPException(status_code=404, detail="Бригада не найдена") from error


@router.put("/{id}/members", response_model=BrigadeRead)
def replace_brigade_members(
    id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    data: BrigadeMembersUpdate,
    session: DatabaseSession,
    _: CurrentObserver,
) -> BrigadeRead:
    try:
        return service.replace_brigade_members(session, id, data)
    except service.BrigadeNotFoundError as error:
        raise HTTPException(status_code=404, detail="Бригада не найдена") from error
    except service.ForemanAlreadyAssignedError as error:
        raise HTTPException(
            status_code=409, detail="Бригадир уже руководит другой бригадой"
        ) from error
    except service.WorkerAlreadyAssignedError as error:
        raise HTTPException(
            status_code=409, detail="Исполнитель уже состоит в другой бригаде"
        ) from error
    except service.BrigadeConflictError as error:
        raise HTTPException(
            status_code=409, detail="Конфликт состава или руководителя бригады"
        ) from error
    except (service.ForemanInvalidError, service.WorkerNotFoundError) as error:
        raise HTTPException(
            status_code=422, detail="Указаны недопустимые бригадир или исполнители"
        ) from error

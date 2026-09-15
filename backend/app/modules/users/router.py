"""HTTP endpoints for users, worker profiles, and skills."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.auth.dependencies import get_current_user, require_roles
from app.modules.users import service
from app.modules.users.enums import UserRole
from app.modules.users.schemas import (
    UserCreate,
    UserRead,
    UserUpdate,
    WorkerSkillCreate,
    WorkerSkillRead,
)

router = APIRouter(prefix="/api/v1/users", tags=["users"])
skills_router = APIRouter(prefix="/api/v1/worker/skills", tags=["skills"])

DatabaseSession = Annotated[Session, Depends(get_session)]
CurrentUser = Annotated[UserRead, Depends(get_current_user)]
RequireObserver = Annotated[UserRead, Depends(require_roles(UserRole.OBSERVER))]


@router.get("/me", response_model=UserRead)
def get_current_user_profile(current_user: CurrentUser) -> UserRead:
    """Получить профиль текущего авторизованного пользователя (включая смену и навыки)."""
    return current_user


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    data: UserCreate,
    session: DatabaseSession,
    response: Response,
    _: RequireObserver,
) -> UserRead:
    """Создать нового пользователя (наблюдателя или исполнителя). Доступно только роли observer."""
    try:
        created_user = service.create_user(session, data)
    except service.UsernameAlreadyExistsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Пользователь с логином '{data.username}' уже существует",
        ) from error

    response.headers["Location"] = f"/api/v1/users/{created_user.id}"
    return created_user


@router.get("", response_model=list[UserRead])
def list_users(
    session: DatabaseSession,
    _: CurrentUser,
    role: UserRole | None = None,
) -> list[UserRead]:
    """Получить список всех пользователей системы. Доступно всем авторизованным пользователям."""
    return service.list_users(session, role)


@router.get(
    "/{id}",
    response_model=UserRead,
    responses={404: {"description": "Пользователь не найден"}},
)
def get_user_by_id(
    id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    session: DatabaseSession,
    _: CurrentUser,
) -> UserRead:
    """Получить данные пользователя по его числовому ID.

    Доступно всем авторизованным пользователям.
    """
    try:
        return service.get_user(session, id)
    except service.UserNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден",
        ) from error


@router.patch(
    "/{id}",
    response_model=UserRead,
    responses={
        404: {"description": "Пользователь не найден"},
        409: {"description": "Пользователь с таким логином уже существует"},
    },
)
def update_user(
    id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    data: UserUpdate,
    session: DatabaseSession,
    _: RequireObserver,
) -> UserRead:
    """Изменить данные любого пользователя. Доступно только роли observer."""
    try:
        return service.update_user(session, id, data)
    except service.UserNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден",
        ) from error
    except service.UsernameAlreadyExistsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Пользователь с логином '{data.username}' уже существует",
        ) from error


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        400: {"description": "Нельзя удалить собственный аккаунт"},
        404: {"description": "Пользователь не найден"},
    },
)
def delete_user(
    id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    session: DatabaseSession,
    current_user: RequireObserver,
) -> Response:
    """Удалить пользователя из системы. Доступно только роли observer."""
    try:
        service.delete_user(session, id, current_user_id=current_user.id)
    except service.CannotDeleteSelfError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нельзя удалить собственный аккаунт",
        ) from error
    except service.UserNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден",
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@skills_router.get("", response_model=list[WorkerSkillRead])
def list_skills(
    session: DatabaseSession,
    _: CurrentUser,
) -> list[WorkerSkillRead]:
    """Получить полный справочник профессиональных навыков.

    Доступно всем авторизованным пользователям.
    """
    return service.get_all_skills(session)


@skills_router.post(
    "",
    response_model=WorkerSkillRead,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"description": "Навык уже существует"}},
)
def create_skill(
    data: WorkerSkillCreate,
    session: DatabaseSession,
    response: Response,
    _: RequireObserver,
) -> WorkerSkillRead:
    """Создать новый навык в справочнике. Доступно только роли observer."""
    try:
        created_skill = service.create_skill(session, data)
    except service.SkillAlreadyExistsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Навык '{data.skill}' уже существует в справочнике",
        ) from error

    response.headers["Location"] = f"/api/v1/worker/skills/{created_skill.id}"
    return created_skill

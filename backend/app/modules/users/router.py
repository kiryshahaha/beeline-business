"""HTTP endpoints for users, worker profiles, and skills."""

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.auth.dependencies import get_current_user, require_roles
from app.modules.execution import day_state
from app.modules.execution.schemas import WorkerDayStateRead, WorkerUnavailableCommand
from app.modules.users import service
from app.modules.users.enums import UserRole
from app.modules.users.schemas import (
    UserCreate,
    UserRead,
    UserUpdate,
    WorkerLineStatusRead,
    WorkerLineStatusUpdate,
    WorkerSkillCreate,
    WorkerSkillRead,
)

router = APIRouter(prefix="/api/v1/users", tags=["users"])
skills_router = APIRouter(prefix="/api/v1/worker/skills", tags=["skills"])
workers_router = APIRouter(prefix="/api/v1/workers", tags=["workers"])

DatabaseSession = Annotated[Session, Depends(get_session)]
CurrentUser = Annotated[UserRead, Depends(get_current_user)]
RequireObserver = Annotated[UserRead, Depends(require_roles(UserRole.OBSERVER))]
IdempotencyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]
UserId = Annotated[int, Path(ge=1, le=2_147_483_647)]

# Stable names for the history counted by users.repository.find_history_links.
HISTORY_LABELS = {
    "routes": "маршруты",
    "planning_plan_routes": "маршруты применённых планов",
    "planning_plans": "рассчитанные планы",
    "day_plan_revisions": "ревизии плана дня",
    "tickets": "назначения заявок",
    "worker_day_states": "состояния рабочего дня",
    "work_events": "события выполнения",
    "ticket_comments": "комментарии",
    "work_type_planning_rules": "правила видов работ",
}


def active_work_conflict(error: service.WorkerHasActiveWorkError) -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        detail={
            "code": "worker_has_active_work",
            "message": (
                "Сначала передайте другим исполнителям активные заявки и сдайте оборудование: "
                "после этого исполнитель перестанет получать работу, история сохранится"
            ),
            **error.work,
        },
    )


@workers_router.put(
    "/{worker_id}/line-status",
    response_model=WorkerLineStatusRead,
    responses={404: {"description": "Исполнитель не найден"}},
)
def update_worker_line_status(
    worker_id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    data: WorkerLineStatusUpdate,
    session: DatabaseSession,
    current_user: RequireObserver,
    idempotency_key: IdempotencyHeader = None,
) -> WorkerLineStatusRead:
    """Снять исполнителя с линии либо вручную вернуть его в доступные."""
    try:
        return service.update_worker_line_status(
            session,
            worker_id,
            data.is_on_line,
            actor_id=current_user.id,
            idempotency_key=idempotency_key.strip() if idempotency_key else None,
        )
    except service.WorkerNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Исполнитель не найден",
        ) from error
    except Exception as error:
        from app.modules.execution.service import IdempotencyConflict

        if isinstance(error, IdempotencyConflict):
            raise HTTPException(
                status_code=409,
                detail={"code": "idempotency_conflict", "event_id": error.event_id},
            ) from error
        raise


@workers_router.post("/{worker_id}/unavailable", response_model=WorkerDayStateRead)
def mark_worker_unavailable(
    worker_id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    data: WorkerUnavailableCommand,
    session: DatabaseSession,
    current_user: RequireObserver,
    idempotency_key: IdempotencyHeader = None,
) -> WorkerDayStateRead:
    if idempotency_key is None or not idempotency_key.strip() or len(idempotency_key) > 128:
        raise HTTPException(
            status_code=422, detail="Требуется непустой Idempotency-Key длиной до 128 символов"
        )
    try:
        state, _ = day_state.mark_worker_unavailable(
            session,
            worker_id,
            data,
            actor_id=current_user.id,
            idempotency_key=idempotency_key.strip(),
        )
        return state
    except day_state.WorkerNotFound as error:
        raise HTTPException(status_code=404, detail="Исполнитель не найден") from error
    except day_state.DistrictNotFound as error:
        raise HTTPException(status_code=404, detail="Район не найден") from error
    except day_state.DayStateRevisionConflict as error:
        raise HTTPException(
            status_code=409,
            detail={"code": error.code, "current_revision": error.current_revision},
        ) from error
    except day_state.IdempotencyConflict as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "idempotency_conflict", "event_id": error.event_id},
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@workers_router.get("/{worker_id}/day-state", response_model=WorkerDayStateRead)
def get_worker_day_state(
    worker_id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    session: DatabaseSession,
    _: RequireObserver,
    district_id: Annotated[int, Query(ge=1, le=2_147_483_647)],
    route_date: Annotated[date | None, Query(alias="date")] = None,
    at: Annotated[datetime | None, Query()] = None,
) -> WorkerDayStateRead:
    if route_date is None:
        raise HTTPException(status_code=422, detail="Требуется date")
    if at is not None and (at.tzinfo is None or at.utcoffset() is None):
        raise HTTPException(status_code=422, detail="Параметр at должен содержать часовой пояс")
    moment = at or datetime.now(UTC)
    try:
        return day_state.day_state_at(session, worker_id, district_id, route_date, moment)
    except day_state.WorkerNotFound as error:
        raise HTTPException(status_code=404, detail="Исполнитель не найден") from error
    except day_state.DistrictNotFound as error:
        raise HTTPException(status_code=404, detail="Район не найден") from error


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
    """Создать пользователя с ролью observer, foreman или worker. Доступно только роли observer."""
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
    current_user: CurrentUser,
    role: UserRole | None = None,
    brigade_id: Annotated[int | None, Query(ge=1, le=2_147_483_647)] = None,
    include_archived: Annotated[
        bool, Query(description="Показать и архивные учётные записи.")
    ] = False,
) -> list[UserRead]:
    """Получить список пользователей с необязательными фильтрами роли и бригады.

    Наблюдатель и исполнитель видят весь каталог. Бригадир получает себя и
    исполнителей своей бригады. Параметр brigade_id сужает выдачу для каждой роли.
    Архивные учётные записи скрыты, пока не передан include_archived=true.
    """
    return service.list_users(session, current_user, role, brigade_id, include_archived)


@router.get(
    "/{id}",
    response_model=UserRead,
    responses={404: {"description": "Пользователь не найден"}},
)
def get_user_by_id(
    id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    session: DatabaseSession,
    current_user: CurrentUser,
) -> UserRead:
    """Получить данные пользователя по его числовому ID.

    Наблюдатель и исполнитель видят любого пользователя. Бригадир видит себя и
    исполнителей своей бригады. Недоступный
    пользователь возвращается как 404.
    """
    try:
        return service.get_user(session, id, current_user)
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
    except service.ActiveForemanError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Нельзя изменить роль бригадира, пока он руководит бригадой",
        ) from error
    except service.WorkerProfileRoleError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Профиль исполнителя доступен только для роли worker",
        ) from error
    except service.WorkerProfileRequiredError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Для назначения роли worker нужны смена и хотя бы один навык",
        ) from error
    except service.WorkerHasActiveWorkError as error:
        raise active_work_conflict(error) from error


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        400: {"description": "Нельзя удалить собственный аккаунт"},
        404: {"description": "Пользователь не найден"},
        409: {
            "description": (
                "Активный бригадир или у пользователя есть история (`user_has_history`, "
                "`links` — число строк по таблицам): используйте архивирование"
            )
        },
    },
)
def delete_user(
    id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    session: DatabaseSession,
    current_user: RequireObserver,
) -> Response:
    """Удалить пользователя без истории. Доступно только роли observer.

    Учётную запись с планами, маршрутами, назначениями, событиями или комментариями
    удалить нельзя — для неё есть POST /api/v1/users/{id}/archive.
    """
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
    except service.ActiveForemanError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Нельзя удалить бригадира, пока он руководит бригадой",
        ) from error
    except service.UserHasHistoryError as error:
        names = ", ".join(HISTORY_LABELS.get(table, table) for table in error.links)
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "user_has_history",
                "message": (
                    f"Удаление стёрло бы историю ({names}). "
                    f"Архивируйте учётную запись: POST /api/v1/users/{id}/archive"
                ),
                "links": error.links,
            },
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{id}/archive",
    response_model=UserRead,
    responses={
        400: {"description": "Нельзя архивировать собственный аккаунт"},
        404: {"description": "Пользователь не найден"},
        409: {
            "description": (
                "Активный бригадир или у исполнителя активные заявки/оборудование на руках "
                "(`worker_has_active_work`)"
            )
        },
    },
)
def archive_user(id: UserId, session: DatabaseSession, current_user: RequireObserver) -> UserRead:
    """Архивировать учётную запись вместо удаления. Доступно только роли observer.

    Вход, обновление токенов, ссылка календаря и push-подписки прекращаются, членство
    в бригаде заканчивается. Профиль исполнителя, планы, маршруты, назначения и события
    сохраняются и читаются как прежде. Архивный исполнитель не назначается вручную и
    исключается из новых расчётов. Повторный вызов возвращает ту же запись.
    """
    try:
        return service.archive_user(session, id, current_user.id)
    except service.CannotArchiveSelfError as error:
        raise HTTPException(400, detail="Нельзя архивировать собственный аккаунт") from error
    except service.UserNotFoundError as error:
        raise HTTPException(404, detail="Пользователь не найден") from error
    except service.ActiveForemanError as error:
        raise HTTPException(
            409, detail="Нельзя архивировать бригадира, пока он руководит бригадой"
        ) from error
    except service.WorkerHasActiveWorkError as error:
        raise active_work_conflict(error) from error


@router.post(
    "/{id}/restore",
    response_model=UserRead,
    responses={404: {"description": "Пользователь не найден"}},
)
def restore_user(id: UserId, session: DatabaseSession, _: RequireObserver) -> UserRead:
    """Вернуть учётную запись из архива. Бригаду и ссылку календаря нужно задать заново."""
    try:
        return service.restore_user(session, id)
    except service.UserNotFoundError as error:
        raise HTTPException(404, detail="Пользователь не найден") from error


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

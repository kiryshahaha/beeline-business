"""Read-only day timeline for dispatchers and brigade foremen."""

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.auth.dependencies import require_roles
from app.modules.schedule import service
from app.modules.schedule.schemas import ScheduleRead
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/api/v1/schedule", tags=["schedule"])
DatabaseSession = Annotated[Session, Depends(get_session)]
CurrentObserverOrForeman = Annotated[
    UserRead, Depends(require_roles(UserRole.OBSERVER, UserRole.FOREMAN))
]


@router.get("", response_model=ScheduleRead, responses={404: {"description": "Офис не найден"}})
def get_schedule(
    session: DatabaseSession,
    current_user: CurrentObserverOrForeman,
    date: Annotated[
        dt.date | None,
        Query(
            ge=dt.date(2000, 1, 1),
            le=dt.date(2100, 12, 31),
            description="Сутки по Москве в формате YYYY-MM-DD; по умолчанию сегодня.",
        ),
    ] = None,
    office_id: Annotated[
        int | None, Query(ge=1, le=2_147_483_647, description="ID офиса бригад.")
    ] = None,
) -> ScheduleRead:
    """Получить бригады и исполнителей со сменами и заявками на сутки для таймлайна.

    Наблюдатель видит все бригады, бригадир — только свою; office_id сужает выдачу.
    Смена хранится как время суток и повторяется каждый день: выходных в модели нет.
    """
    try:
        return service.get_schedule(session, date or service.today(), office_id, current_user)
    except service.OfficeNotFoundError as error:
        raise HTTPException(status_code=404, detail="Офис не найден") from error

"""API for creating and retrieving addresses."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.auth.dependencies import require_roles
from app.modules.locations import service
from app.modules.locations.schemas import LocationCreate, LocationRead
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/api/v1/location", tags=["locations"])
DatabaseSession = Annotated[Session, Depends(get_session)]
CurrentObserver = Annotated[UserRead, Depends(require_roles(UserRole.OBSERVER))]


@router.post("", response_model=LocationRead, status_code=status.HTTP_201_CREATED)
def create_location(
    data: LocationCreate, session: DatabaseSession, _observer: CurrentObserver
) -> LocationRead:
    """Создать или получить существующий адрес из справочника."""
    return service.get_or_create_location(session, data)

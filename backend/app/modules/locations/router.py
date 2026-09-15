"""API for creating and retrieving addresses."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.locations import service
from app.modules.locations.schemas import LocationCreate, LocationRead

router = APIRouter(prefix="/api/v1/location", tags=["locations"])
DatabaseSession = Annotated[Session, Depends(get_session)]


@router.post("", response_model=LocationRead, status_code=status.HTTP_201_CREATED)
def create_location(data: LocationCreate, session: DatabaseSession) -> LocationRead:
    """Создать или получить существующий адрес из справочника."""
    return service.get_or_create_location(session, data)

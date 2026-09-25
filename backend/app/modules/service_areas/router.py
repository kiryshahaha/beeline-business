"""FastAPI routes for service areas."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.auth.dependencies import get_current_user
from app.modules.service_areas import service
from app.modules.service_areas.schemas import ServiceAreaRead
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/api/v1/service-areas", tags=["service-areas"])


@router.get("", response_model=list[ServiceAreaRead])
def list_service_areas(
    session: Session = Depends(get_session),
    _: UserRead = Depends(get_current_user),
) -> list[ServiceAreaRead]:
    return service.get_all_service_areas(session)


@router.get("/{service_area_id}", response_model=ServiceAreaRead)
def get_service_area(
    service_area_id: int,
    session: Session = Depends(get_session),
    _: UserRead = Depends(get_current_user),
) -> ServiceAreaRead:
    area = service.get_service_area_by_id(session, service_area_id)
    if area is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service area not found")
    return area

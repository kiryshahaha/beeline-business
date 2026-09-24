"""Service layer for service areas."""

from sqlalchemy.orm import Session

from app.modules.service_areas import repository
from app.modules.service_areas.models import ServiceArea
from app.modules.service_areas.schemas import ServiceAreaRead


def get_all_service_areas(session: Session) -> list[ServiceAreaRead]:
    areas = repository.list_service_areas(session)
    return [ServiceAreaRead.model_validate(a) for a in areas]


def get_service_area_by_id(session: Session, service_area_id: int) -> ServiceAreaRead | None:
    area = repository.get_service_area(session, service_area_id)
    if area is None:
        return None
    return ServiceAreaRead.model_validate(area)


def get_or_create_service_area(
    session: Session, code: str, name: str, description: str | None = None
) -> ServiceArea:
    existing = repository.find_by_code(session, code)
    if existing is not None:
        return existing
    return repository.create_service_area(
        session, {"code": code, "name": name, "description": description}
    )

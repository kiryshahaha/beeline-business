"""Database operations for service areas."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.service_areas.models import ServiceArea


def list_service_areas(session: Session) -> list[ServiceArea]:
    return list(session.scalars(select(ServiceArea).order_by(ServiceArea.id)))


def get_service_area(session: Session, service_area_id: int) -> ServiceArea | None:
    return session.get(ServiceArea, service_area_id)


def find_by_code(session: Session, code: str) -> ServiceArea | None:
    return session.scalar(
        select(ServiceArea).where(func.lower(ServiceArea.code) == code.strip().lower())
    )


def create_service_area(session: Session, data: dict) -> ServiceArea:
    area = ServiceArea(**data)
    session.add(area)
    session.flush()
    return area

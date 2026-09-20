"""Business logic for office management."""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.planning_guard import lock_planning_mutation
from app.modules.offices import repository
from app.modules.offices.schemas import OfficeCreate, OfficeRead


def create_office(session: Session, office_in: OfficeCreate) -> OfficeRead:
    # Optional: could check if location_id exists in locations,
    # but Postgres foreign key will enforce it.
    try:
        lock_planning_mutation(session)
        office_id = repository.add_office(session, office_in.name, office_in.location_id)
        session.commit()
    except Exception as e:
        session.rollback()
        # In a real system, you might want to catch IntegrityError explicitly
        # and raise 400 or 409 if name already exists or building_id is invalid.
        if "uq_offices_name" in str(e):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Офис с таким названием уже существует",
            )
        if "fk_offices_location_id" in str(e) or "locations" in str(e):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Локация с таким ID не найдена",
            )
        raise

    row = repository.find_office_by_id(session, office_id)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve created office",
        )
    return OfficeRead.model_validate(row)


def list_offices(session: Session) -> list[OfficeRead]:
    rows = repository.list_offices(session)
    return [OfficeRead.model_validate(row) for row in rows]


def get_office(session: Session, office_id: int) -> OfficeRead:
    row = repository.find_office_by_id(session, office_id)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Офис не найден",
        )
    return OfficeRead.model_validate(row)

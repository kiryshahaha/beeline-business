"""REST endpoints for offices."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.auth.dependencies import require_roles
from app.modules.offices import service
from app.modules.offices.schemas import OfficeCreate, OfficeRead
from app.modules.users.enums import UserRole

router = APIRouter(prefix="/api/v1/offices", tags=["offices"])


@router.post("/", response_model=OfficeRead, status_code=201)
def create_office(
    office_in: OfficeCreate,
    session: Annotated[Session, Depends(get_session)],
    _viewer_id: Annotated[int, Depends(require_roles(UserRole.OBSERVER))],
):
    """Create a new office (only accessible to OBSERVER role typically, acting as admin/dispatcher)."""  # noqa: E501
    return service.create_office(session, office_in)


@router.get("/", response_model=list[OfficeRead])
def list_offices(
    session: Annotated[Session, Depends(get_session)],
    _viewer_id: Annotated[int, Depends(require_roles(UserRole.OBSERVER, UserRole.WORKER))],
):
    """List all offices."""
    return service.list_offices(session)


@router.get("/{office_id}", response_model=OfficeRead)
def get_office(
    office_id: int,
    session: Annotated[Session, Depends(get_session)],
    _viewer_id: Annotated[int, Depends(require_roles(UserRole.OBSERVER, UserRole.WORKER))],
):
    """Get a specific office by ID."""
    return service.get_office(session, office_id)

"""Read the work type reference without HTTP-specific exceptions."""

from sqlalchemy.orm import Session

from app.modules.work_types import repository
from app.modules.work_types.schemas import WorkTypeRead


class WorkTypeNotFoundError(Exception):
    pass


def list_work_types(session: Session) -> list[WorkTypeRead]:
    return [WorkTypeRead.model_validate(row) for row in repository.list_work_types(session)]


def get_work_type(session: Session, work_type_id: int) -> WorkTypeRead:
    row = repository.find_work_type(session, work_type_id)
    if row is None:
        raise WorkTypeNotFoundError
    return WorkTypeRead.model_validate(row)

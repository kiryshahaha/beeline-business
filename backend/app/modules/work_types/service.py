"""Read, create and edit work types without HTTP-specific exceptions."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.planning_guard import lock_planning_mutation
from app.modules.work_types import repository
from app.modules.work_types.schemas import (
    NORM_PARTS,
    WorkTypeCreate,
    WorkTypeRead,
    WorkTypeUpdate,
)


class WorkTypeNotFoundError(Exception):
    pass


class WorkTypeNameAlreadyExistsError(Exception):
    pass


class WorkTypeNormNotPositiveError(Exception):
    pass


def list_work_types(session: Session) -> list[WorkTypeRead]:
    return [WorkTypeRead.model_validate(row) for row in repository.list_work_types(session)]


def get_work_type(session: Session, work_type_id: int) -> WorkTypeRead:
    row = repository.find_work_type(session, work_type_id)
    if row is None:
        raise WorkTypeNotFoundError
    return WorkTypeRead.model_validate(row)


def create_work_type(session: Session, data: WorkTypeCreate) -> WorkTypeRead:
    try:
        with session.begin():
            lock_planning_mutation(session)
            if repository.find_id_by_name(session, data.name) is not None:
                raise WorkTypeNameAlreadyExistsError
            if data.code and repository.find_id_by_code(session, data.code) is not None:
                raise WorkTypeNameAlreadyExistsError
            work_type_id = repository.add_work_type(session, data.model_dump())
            return get_work_type(session, work_type_id)
    except IntegrityError as error:
        # A parallel request inserted the same name/code after the check above.
        raise WorkTypeNameAlreadyExistsError from error


def update_work_type(session: Session, work_type_id: int, data: WorkTypeUpdate) -> WorkTypeRead:
    changes = data.model_dump(exclude_unset=True)
    try:
        with session.begin():
            lock_planning_mutation(session)
            current = repository.lock_work_type(session, work_type_id)
            if current is None:
                raise WorkTypeNotFoundError
            if "name" in changes and repository.find_id_by_name(session, changes["name"]) not in (
                None,
                work_type_id,
            ):
                raise WorkTypeNameAlreadyExistsError
            if "code" in changes and changes["code"]:
                code_owner = repository.find_id_by_code(session, changes["code"])
                if code_owner not in (None, work_type_id):
                    raise WorkTypeNameAlreadyExistsError
            if sum(changes.get(part, current[part]) for part in NORM_PARTS) == 0:
                raise WorkTypeNormNotPositiveError
            repository.update_work_type(session, work_type_id, changes)
            return get_work_type(session, work_type_id)
    except IntegrityError as error:
        raise WorkTypeNameAlreadyExistsError from error


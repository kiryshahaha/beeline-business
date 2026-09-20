"""Business rules and transaction boundaries for brigade management."""

from sqlalchemy import RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.planning_guard import lock_planning_mutation
from app.modules.brigades import repository
from app.modules.brigades.schemas import BrigadeCreate, BrigadeMembersUpdate, BrigadeRead
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead


class BrigadeNotFoundError(Exception):
    pass


class BrigadeNameAlreadyExistsError(Exception):
    pass


class ForemanInvalidError(Exception):
    pass


class ForemanAlreadyAssignedError(Exception):
    pass


class WorkerNotFoundError(Exception):
    pass


class WorkerAlreadyAssignedError(Exception):
    pass


class BrigadeConflictError(Exception):
    pass


def _build_read(row: RowMapping) -> BrigadeRead:
    return BrigadeRead(
        id=row["id"],
        name=row["name"],
        foreman_id=row["foreman_id"],
        office_id=row["office_id"],
        worker_ids=list(row["worker_ids"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _validate_foreman(session: Session, foreman_id: int, brigade_id: int | None = None) -> None:
    if repository.lock_user_role(session, foreman_id) != UserRole.FOREMAN.value:
        raise ForemanInvalidError
    assigned = repository.find_brigade_by_foreman(session, foreman_id)
    if assigned is not None and assigned["id"] != brigade_id:
        raise ForemanAlreadyAssignedError


def _validate_workers(
    session: Session, worker_ids: list[int], excluded_brigade_id: int | None = None
) -> None:
    if repository.find_worker_ids(session, worker_ids) != set(worker_ids):
        raise WorkerNotFoundError
    if repository.find_occupied_worker_ids(session, worker_ids, excluded_brigade_id):
        raise WorkerAlreadyAssignedError


def create_brigade(session: Session, data: BrigadeCreate) -> BrigadeRead:
    try:
        with session.begin():
            lock_planning_mutation(session)
            if repository.find_brigade_by_name(session, data.name) is not None:
                raise BrigadeNameAlreadyExistsError
            _validate_foreman(session, data.foreman_id)
            _validate_workers(session, data.worker_ids)
            brigade_id = repository.add_brigade(session, data.name, data.foreman_id, data.office_id)
            repository.add_brigade_members(session, brigade_id, data.worker_ids)
            row = repository.find_brigade_by_id(session, brigade_id)
            if row is None:
                raise RuntimeError("Created brigade was not found")
            return _build_read(row)
    except IntegrityError as error:
        raise BrigadeConflictError from error


def replace_brigade_members(
    session: Session, brigade_id: int, data: BrigadeMembersUpdate
) -> BrigadeRead:
    try:
        with session.begin():
            lock_planning_mutation(session)
            existing = repository.lock_brigade_by_id(session, brigade_id)
            if existing is None:
                raise BrigadeNotFoundError
            _validate_foreman(session, data.foreman_id, brigade_id)
            _validate_workers(session, data.worker_ids, brigade_id)
            if data.foreman_id != existing["foreman_id"] or data.office_id != existing["office_id"]:
                repository.update_brigade_foreman_and_office(
                    session, brigade_id, data.foreman_id, data.office_id
                )
            repository.delete_brigade_members(session, brigade_id)
            repository.add_brigade_members(session, brigade_id, data.worker_ids)
            row = repository.find_brigade_by_id(session, brigade_id)
            if row is None:
                raise RuntimeError("Updated brigade was not found")
            return _build_read(row)
    except IntegrityError as error:
        raise BrigadeConflictError from error


def list_brigades(session: Session, current_user: UserRead) -> list[BrigadeRead]:
    return [
        _build_read(row)
        for row in repository.list_visible_brigades(
            session, current_user.id, current_user.role.value
        )
    ]


def get_brigade(session: Session, brigade_id: int, current_user: UserRead) -> BrigadeRead:
    row = repository.find_visible_brigade(
        session, brigade_id, current_user.id, current_user.role.value
    )
    if row is None:
        raise BrigadeNotFoundError
    return _build_read(row)

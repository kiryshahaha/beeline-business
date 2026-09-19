"""User management, skill catalog, and worker profile service."""

from sqlalchemy import RowMapping
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.modules.users import repository
from app.modules.users.enums import TransportType, UserRole
from app.modules.users.schemas import (
    UserCreate,
    UserRead,
    UserUpdate,
    WorkerProfileRead,
    WorkerSkillCreate,
    WorkerSkillRead,
)


class UserNotFoundError(Exception):
    pass


class UsernameAlreadyExistsError(Exception):
    pass


class SkillAlreadyExistsError(Exception):
    pass


class CannotDeleteSelfError(Exception):
    pass


class ActiveForemanError(Exception):
    pass


class WorkerProfileRoleError(Exception):
    pass


class WorkerProfileRequiredError(Exception):
    pass


def _build_user_read(row: RowMapping) -> UserRead:
    worker_profile = None
    if row["role"] == UserRole.WORKER.value and row["workshift_start"] is not None:
        worker_profile = WorkerProfileRead(
            workshift_start=row["workshift_start"],
            workshift_end=row["workshift_end"],
            skills=list(row["skills"]),
            transport_type=row["transport_type"],
        )
    return UserRead(
        id=row["id"],
        name=row["name"],
        surname=row["surname"],
        lastname=row["lastname"],
        username=row["username"],
        role=UserRole(row["role"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        worker_profile=worker_profile,
        brigade_id=row["brigade_id"],
        brigade_name=row["brigade_name"],
    )


def get_user(session: Session, user_id: int, current_user: UserRead | None = None) -> UserRead:
    row = repository.find_user_by_id(
        session,
        user_id,
        viewer_id=current_user.id if current_user else None,
        viewer_role=current_user.role.value if current_user else None,
    )
    if row is None:
        raise UserNotFoundError
    return _build_user_read(row)


def list_users(
    session: Session,
    current_user: UserRead | None = None,
    role: UserRole | None = None,
    brigade_id: int | None = None,
) -> list[UserRead]:
    rows = repository.list_users(
        session,
        role=role.value if role else None,
        brigade_id=brigade_id,
        viewer_id=current_user.id if current_user else None,
        viewer_role=current_user.role.value if current_user else None,
    )
    return [_build_user_read(row) for row in rows]


def create_user(session: Session, data: UserCreate) -> UserRead:
    with session.begin():
        if repository.find_user_by_username(session, data.username) is not None:
            raise UsernameAlreadyExistsError

        password_hash = hash_password(data.password)
        user_id = repository.add_user(
            session,
            {
                "name": data.name,
                "surname": data.surname,
                "lastname": data.lastname,
                "username": data.username,
                "password_hash": password_hash,
                "role": data.role.value,
            },
        )

        if data.role == UserRole.WORKER and data.worker_profile is not None:
            profile = data.worker_profile
            repository.add_worker(
                session,
                {
                    "user_id": user_id,
                    "workshift_start": profile.workshift_start,
                    "workshift_end": profile.workshift_end,
                    "transport_type": profile.transport_type.value,
                },
            )
            for skill_name in profile.skills:
                skill_id = repository.ensure_skill(session, skill_name)
                repository.assign_worker_skill(session, user_id, skill_id)

        return get_user(session, user_id)


def create_skill(session: Session, data: WorkerSkillCreate) -> WorkerSkillRead:
    with session.begin():
        if repository.find_skill_by_name(session, data.skill) is not None:
            raise SkillAlreadyExistsError
        skill_id = repository.add_skill(session, data.skill)
        return WorkerSkillRead(id=skill_id, skill=data.skill)


def get_all_skills(session: Session) -> list[WorkerSkillRead]:
    rows = repository.list_skills(session)
    return [WorkerSkillRead(id=row["id"], skill=row["skill"]) for row in rows]


def update_user(session: Session, user_id: int, data: UserUpdate) -> UserRead:
    with session.begin():
        existing_user = repository.find_user_by_id(session, user_id)
        if existing_user is None:
            raise UserNotFoundError

        if data.username is not None and data.username.lower() != existing_user["username"].lower():
            conflict = repository.find_user_by_username(session, data.username)
            if conflict is not None and conflict["id"] != user_id:
                raise UsernameAlreadyExistsError

        dump = data.model_dump(exclude_unset=True)
        user_values: dict[str, object] = {}
        if "name" in dump and data.name is not None:
            user_values["name"] = data.name
        if "surname" in dump and data.surname is not None:
            user_values["surname"] = data.surname
        if "lastname" in dump:
            user_values["lastname"] = data.lastname
        if "username" in dump and data.username is not None:
            user_values["username"] = data.username
        if "password" in dump and data.password is not None:
            user_values["password_hash"] = hash_password(data.password)

        new_role = data.role if data.role is not None else UserRole(existing_user["role"])
        if data.worker_profile is not None and new_role != UserRole.WORKER:
            raise WorkerProfileRoleError
        if new_role == UserRole.WORKER and existing_user["role"] != UserRole.WORKER.value:
            profile = data.worker_profile
            if (
                profile is None
                or profile.workshift_start is None
                or profile.workshift_end is None
                or not profile.skills
            ):
                raise WorkerProfileRequiredError
        if data.role is not None:
            user_values["role"] = data.role.value

        if user_values:
            repository.update_user(session, user_id, user_values)

        if (
            existing_user["role"] == UserRole.FOREMAN.value
            and new_role != UserRole.FOREMAN
            and repository.foreman_manages_brigade(session, user_id)
        ):
            raise ActiveForemanError

        if new_role in (UserRole.OBSERVER, UserRole.FOREMAN):
            if existing_user["role"] == UserRole.WORKER.value:
                repository.delete_worker(session, user_id)
        elif new_role == UserRole.WORKER:
            worker_dump = (
                data.worker_profile.model_dump(exclude_unset=True) if data.worker_profile else {}
            )
            shift_start = worker_dump.get("workshift_start") or existing_user["workshift_start"]
            shift_end = worker_dump.get("workshift_end") or existing_user["workshift_end"]

            if shift_start is not None and shift_end is not None:
                if shift_start == shift_end:
                    raise ValueError("Начало и окончание рабочей смены не могут совпадать")
                repository.upsert_worker(
                    session,
                    user_id,
                    {
                        "workshift_start": shift_start,
                        "workshift_end": shift_end,
                        "transport_type": worker_dump.get("transport_type")
                        or existing_user["transport_type"]
                        or TransportType.WALKING.value,
                    },
                )

            if "skills" in worker_dump and worker_dump["skills"] is not None:
                repository.clear_worker_skills(session, user_id)
                for skill_name in worker_dump["skills"]:
                    skill_id = repository.ensure_skill(session, skill_name)
                    repository.assign_worker_skill(session, user_id, skill_id)

        return get_user(session, user_id)


def delete_user(session: Session, user_id: int, current_user_id: int | None = None) -> None:
    if current_user_id is not None and user_id == current_user_id:
        raise CannotDeleteSelfError

    with session.begin():
        if repository.foreman_manages_brigade(session, user_id):
            raise ActiveForemanError
        deleted = repository.delete_user(session, user_id)
        if not deleted:
            raise UserNotFoundError

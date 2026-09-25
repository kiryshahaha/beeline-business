"""User management, skill catalog, and worker profile service."""

from datetime import UTC, datetime, time
from hashlib import sha256

from sqlalchemy import RowMapping, text
from sqlalchemy.orm import Session

from app.core.planning_guard import lock_planning_mutation
from app.core.security import hash_password
from app.modules.auth import repository as auth_repository
from app.modules.execution.day_state import mark_worker_unavailable
from app.modules.execution.schemas import WorkerUnavailableCommand
from app.modules.users import repository
from app.modules.users.enums import TransportType, UserRole
from app.modules.users.schemas import (
    UserCreate,
    UserRead,
    UserUpdate,
    WorkerLineStatusRead,
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


class WorkerNotFoundError(Exception):
    pass


class CannotArchiveSelfError(Exception):
    pass


class WorkerHasActiveWorkError(Exception):
    """Active tickets or equipment on hand must be handed over before the engineer leaves."""

    def __init__(self, work: dict[str, list]):
        super().__init__("worker_has_active_work")
        self.work = work


class UserHasHistoryError(Exception):
    """Deleting the account would destroy plans, routes or other history; archive it instead."""

    def __init__(self, links: dict[str, int]):
        super().__init__("user_has_history")
        self.links = links


def _build_user_read(row: RowMapping) -> UserRead:
    worker_profile = None
    if row["role"] == UserRole.WORKER.value and row["workshift_start"] is not None:
        worker_profile = WorkerProfileRead(
            workshift_start=row["workshift_start"],
            workshift_end=row["workshift_end"],
            skills=list(row["skills"]),
            transport_type=row["transport_type"],
            is_on_line=row["is_on_line"],
            service_area_id=row["service_area_id"] if "service_area_id" in row else None,
            start_location_id=row["start_location_id"] if "start_location_id" in row else None,
            stock_office_id=row["stock_office_id"] if "stock_office_id" in row else None,
            end_location_id=row["end_location_id"] if "end_location_id" in row else None,
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
        archived_at=row["archived_at"],
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
    include_archived: bool = False,
) -> list[UserRead]:
    rows = repository.list_users(
        session,
        role=role.value if role else None,
        brigade_id=brigade_id,
        viewer_id=current_user.id if current_user else None,
        viewer_role=current_user.role.value if current_user else None,
        include_archived=include_archived,
    )
    return [_build_user_read(row) for row in rows]


def create_user(session: Session, data: UserCreate) -> UserRead:
    with session.begin_nested() if session.in_transaction() else session.begin():
        lock_planning_mutation(session)
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
                    "service_area_id": profile.service_area_id,
                    "start_location_id": profile.start_location_id,
                    "stock_office_id": profile.stock_office_id,
                    "end_location_id": profile.end_location_id,
                },
            )
            for skill_name in profile.skills:
                skill_id = repository.ensure_skill(session, skill_name)
                repository.assign_worker_skill(session, user_id, skill_id)

        return get_user(session, user_id)


def create_skill(session: Session, data: WorkerSkillCreate) -> WorkerSkillRead:
    with session.begin():
        lock_planning_mutation(session)
        if repository.find_skill_by_name(session, data.skill) is not None:
            raise SkillAlreadyExistsError
        skill_id = repository.add_skill(session, data.skill)
        return WorkerSkillRead(id=skill_id, skill=data.skill)


def get_all_skills(session: Session) -> list[WorkerSkillRead]:
    rows = repository.list_skills(session)
    return [WorkerSkillRead(id=row["id"], skill=row["skill"]) for row in rows]


def update_worker_line_status(
    session: Session,
    worker_id: int,
    is_on_line: bool,
    *,
    actor_id: int | None = None,
    idempotency_key: str | None = None,
) -> WorkerLineStatusRead:
    with session.begin():
        lock_planning_mutation(session)
        worker = repository.lock_worker_line_status(session, worker_id)
        if worker is None:
            raise WorkerNotFoundError

        released_ticket_ids: list[int] = []
        if not is_on_line:
            if worker["is_on_line"]:
                contexts = repository.list_worker_day_contexts(session, worker_id)
                for context in contexts:
                    current = session.execute(
                        text(
                            """
                            SELECT revision
                            FROM worker_day_states
                            WHERE worker_id = :worker_id
                              AND district_id = :district_id
                              AND route_date = :route_date
                            FOR UPDATE
                            """
                        ),
                        {
                            "worker_id": worker_id,
                            "district_id": context["district_id"],
                            "route_date": context["route_date"],
                        },
                    ).scalar_one_or_none()
                    command = WorkerUnavailableCommand.model_construct(
                        expected_revision=current or 1,
                        occurred_at=datetime.combine(context["route_date"], time(12), UTC),
                        reason="line_status",
                        expected_available_at=None,
                        worker_id=worker_id,
                        district_id=context["district_id"],
                        route_date=context["route_date"],
                        payload={"source": "line_status"},
                    )
                    context_key = (
                        f"{idempotency_key or f'line-status:{worker_id}'}:"
                        f"{context['district_id']}:{context['route_date']}"
                    )
                    if len(context_key) > 128:
                        context_key = sha256(context_key.encode()).hexdigest()
                    _, released = mark_worker_unavailable(
                        session,
                        worker_id,
                        command,
                        actor_id=actor_id or worker_id,
                        idempotency_key=context_key,
                    )
                    released_ticket_ids.extend(released)
                repository.update_worker_line_status(session, worker_id, False)
            else:
                return WorkerLineStatusRead(
                    worker_id=worker_id,
                    is_on_line=False,
                    released_ticket_ids=[],
                )
        else:
            repository.update_worker_line_status(session, worker_id, True)

        return WorkerLineStatusRead(
            worker_id=worker_id,
            is_on_line=is_on_line,
            released_ticket_ids=released_ticket_ids,
        )


def update_user(session: Session, user_id: int, data: UserUpdate) -> UserRead:
    with session.begin():
        lock_planning_mutation(session)
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
                _retire_worker(session, user_id)
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
                        "service_area_id": (
                            worker_dump["service_area_id"]
                            if "service_area_id" in worker_dump
                            else existing_user["service_area_id"]
                        ),
                        "start_location_id": (
                            worker_dump["start_location_id"]
                            if "start_location_id" in worker_dump
                            else existing_user["start_location_id"]
                        ),
                        "stock_office_id": (
                            worker_dump["stock_office_id"]
                            if "stock_office_id" in worker_dump
                            else existing_user["stock_office_id"]
                        ),
                        "end_location_id": (
                            worker_dump["end_location_id"]
                            if "end_location_id" in worker_dump
                            else existing_user["end_location_id"]
                        ),
                    },
                )

            if "skills" in worker_dump and worker_dump["skills"] is not None:
                repository.clear_worker_skills(session, user_id)
                for skill_name in worker_dump["skills"]:
                    skill_id = repository.ensure_skill(session, skill_name)
                    repository.assign_worker_skill(session, user_id, skill_id)

        if ("password" in dump and data.password is not None) or (
            new_role != UserRole(existing_user["role"])
        ):
            auth_repository.revoke_all_user_tokens(session, user_id)

        return get_user(session, user_id)


def _retire_worker(session: Session, user_id: int) -> None:
    """Stop giving work to the engineer while keeping the profile, routes and assignments.

    The worker row stays as the historical identity referenced by plans, routes, events
    and assignments; the role or the archive mark decides whether new work is allowed.
    """
    work = repository.find_active_work(session, user_id)
    if work["ticket_ids"] or work["equipment_on_hand"]:
        raise WorkerHasActiveWorkError(work)
    repository.end_worker_duties(session, user_id)


def archive_user(session: Session, user_id: int, current_user_id: int) -> UserRead:
    if user_id == current_user_id:
        raise CannotArchiveSelfError
    with session.begin():
        lock_planning_mutation(session)
        user = repository.lock_user(session, user_id)
        if user is None:
            raise UserNotFoundError
        if user["archived_at"] is None:
            if repository.foreman_manages_brigade(session, user_id):
                raise ActiveForemanError
            if user["role"] == UserRole.WORKER.value:
                _retire_worker(session, user_id)
            repository.set_archived(session, user_id, True)
            auth_repository.revoke_all_user_tokens(session, user_id)
            repository.delete_push_subscriptions(session, user_id)
        return get_user(session, user_id)


def restore_user(session: Session, user_id: int) -> UserRead:
    """Return the account to work; brigade membership and calendar link are set up again."""
    with session.begin():
        lock_planning_mutation(session)
        user = repository.lock_user(session, user_id)
        if user is None:
            raise UserNotFoundError
        if user["archived_at"] is not None:
            repository.set_archived(session, user_id, False)
        return get_user(session, user_id)


def delete_user(session: Session, user_id: int, current_user_id: int | None = None) -> None:
    if current_user_id is not None and user_id == current_user_id:
        raise CannotDeleteSelfError

    with session.begin():
        lock_planning_mutation(session)
        if repository.lock_user(session, user_id) is None:
            raise UserNotFoundError
        if repository.foreman_manages_brigade(session, user_id):
            raise ActiveForemanError
        links = repository.find_history_links(session, user_id)
        if links:
            raise UserHasHistoryError(links)
        repository.delete_user(session, user_id)

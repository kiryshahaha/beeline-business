"""Request and response schemas for users, workers, and skills."""

from datetime import time
from typing import Annotated, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.modules.users.enums import TransportType, UserRole

PositiveInt32 = Annotated[int, Field(strict=True, ge=1, le=2_147_483_647)]

WORKER_SKILL_EXAMPLE = {"id": 1, "skill": "Монтаж ВОЛС"}
WORKER_SKILL_CREATE_EXAMPLE = {"skill": "Монтаж ВОЛС"}

WORKER_PROFILE_CREATE_EXAMPLE = {
    "transport_type": "walking",
    "workshift_start": "09:00:00",
    "workshift_end": "18:00:00",
    "skills": ["Монтаж ВОЛС", "Настройка роутеров"],
}

WORKER_PROFILE_READ_EXAMPLE = {
    "transport_type": "walking",
    "workshift_start": "09:00:00",
    "workshift_end": "18:00:00",
    "skills": ["Монтаж ВОЛС", "Настройка роутеров"],
}

USER_CREATE_WORKER_EXAMPLE = {
    "name": "Иван",
    "surname": "Иванов",
    "lastname": "Иванович",
    "username": "ivanov_worker",
    "password": "StrongPassword123!",
    "role": "worker",
    "worker_profile": WORKER_PROFILE_CREATE_EXAMPLE,
}

USER_CREATE_OBSERVER_EXAMPLE = {
    "name": "Анна",
    "surname": "Петрова",
    "lastname": None,
    "username": "petrova_observer",
    "password": "StrongPassword123!",
    "role": "observer",
    "worker_profile": None,
}

USER_CREATE_FOREMAN_EXAMPLE = {
    "name": "Пётр",
    "surname": "Сидоров",
    "lastname": None,
    "username": "sidorov_foreman",
    "password": "StrongPassword123!",
    "role": "foreman",
    "worker_profile": None,
}

USER_READ_WORKER_EXAMPLE = {
    "id": 2,
    "name": "Иван",
    "surname": "Иванов",
    "lastname": "Иванович",
    "username": "ivanov_worker",
    "role": "worker",
    "created_at": "2026-09-13T10:00:00+03:00",
    "updated_at": "2026-09-13T10:00:00+03:00",
    "worker_profile": WORKER_PROFILE_READ_EXAMPLE,
}

USER_READ_OBSERVER_EXAMPLE = {
    "id": 1,
    "name": "Анна",
    "surname": "Петрова",
    "lastname": None,
    "username": "petrova_observer",
    "role": "observer",
    "created_at": "2026-09-13T09:00:00+03:00",
    "updated_at": "2026-09-13T09:00:00+03:00",
    "worker_profile": None,
}

USER_READ_FOREMAN_EXAMPLE = {
    "id": 3,
    "name": "Пётр",
    "surname": "Сидоров",
    "lastname": None,
    "username": "sidorov_foreman",
    "role": "foreman",
    "created_at": "2026-09-13T10:30:00+03:00",
    "updated_at": "2026-09-13T10:30:00+03:00",
    "worker_profile": None,
    "brigade_id": None,
    "brigade_name": None,
}


class WorkerSkillCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [WORKER_SKILL_CREATE_EXAMPLE]}
    )

    skill: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]

    @field_validator("skill")
    @classmethod
    def reject_null_character(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("Название навыка не может содержать нулевой символ")
        return value


class WorkerSkillRead(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [WORKER_SKILL_EXAMPLE]})

    id: PositiveInt32
    skill: str


class WorkerProfileCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [WORKER_PROFILE_CREATE_EXAMPLE]}
    )

    transport_type: TransportType = Field(
        default=TransportType.WALKING, description="Способ передвижения исполнителя"
    )
    workshift_start: time = Field(description="Время начала рабочей смены, например 09:00:00")
    workshift_end: time = Field(
        description=(
            "Время окончания рабочей смены "
            "(поддерживаются ночные смены, например 22:00:00 - 06:00:00)"
        )
    )
    skills: list[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    ] = Field(min_length=1, description="Список профессиональных навыков исполнителя")

    @field_validator("skills")
    @classmethod
    def validate_skills_content(cls, values: list[str]) -> list[str]:
        for skill in values:
            if "\x00" in skill:
                raise ValueError("Навык не может содержать нулевой символ")
        # Remove duplicates while preserving order
        seen = set()
        unique_skills = []
        for s in values:
            if s.lower() not in seen:
                seen.add(s.lower())
                unique_skills.append(s)
        return unique_skills

    @model_validator(mode="after")
    def validate_workshift(self) -> Self:
        if self.workshift_start == self.workshift_end:
            raise ValueError("Начало и окончание рабочей смены не могут совпадать")
        return self


class WorkerProfileRead(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [WORKER_PROFILE_READ_EXAMPLE]})

    workshift_start: time
    workshift_end: time
    skills: list[str]
    transport_type: TransportType = TransportType.WALKING


class UserCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                USER_CREATE_WORKER_EXAMPLE,
                USER_CREATE_OBSERVER_EXAMPLE,
                USER_CREATE_FOREMAN_EXAMPLE,
            ]
        },
    )

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    surname: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    lastname: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
        | None
    ) = None
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=50)]
    password: Annotated[str, StringConstraints(min_length=8, max_length=128)] = Field(
        description="Пароль пользователя (от 8 до 128 символов)"
    )
    role: UserRole = Field(
        description=(
            "Роль пользователя: observer — наблюдатель, "
            "foreman — бригадир, worker — выездной специалист"
        )
    )
    worker_profile: WorkerProfileCreate | None = Field(
        default=None,
        description=(
            "Профиль исполнителя. Обязателен для роли worker и недопустим "
            "для ролей observer и foreman"
        ),
    )

    @field_validator("name", "surname", "lastname", "username", "password")
    @classmethod
    def reject_null_character(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("Поле не может содержать нулевой символ")
        return value

    @model_validator(mode="after")
    def validate_role_profile_coupling(self) -> Self:
        if self.role == UserRole.WORKER:
            if self.worker_profile is None:
                raise ValueError("Профиль worker_profile обязателен для роли worker")
        elif self.role in (UserRole.OBSERVER, UserRole.FOREMAN):
            if self.worker_profile is not None:
                raise ValueError("Профиль worker_profile недопустим для ролей observer и foreman")
        return self


class UserRead(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                USER_READ_WORKER_EXAMPLE,
                USER_READ_OBSERVER_EXAMPLE,
                USER_READ_FOREMAN_EXAMPLE,
            ]
        }
    )

    id: PositiveInt32
    name: str
    surname: str
    lastname: str | None = None
    username: str
    role: UserRole
    created_at: AwareDatetime
    updated_at: AwareDatetime
    worker_profile: WorkerProfileRead | None = None
    brigade_id: PositiveInt32 | None = None
    brigade_name: str | None = None


USER_UPDATE_EXAMPLE = {
    "name": "Иван",
    "surname": "Иванов",
    "lastname": "Иванович",
    "username": "ivanov_updated",
    "password": "NewStrongPassword123!",
    "role": "worker",
    "worker_profile": {
        "workshift_start": "08:00:00",
        "workshift_end": "17:00:00",
        "skills": ["Монтаж ВОЛС", "Аварийно-восстановительные работы"],
    },
}


class WorkerProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transport_type: TransportType = TransportType.WALKING

    workshift_start: time | None = None
    workshift_end: time | None = None
    skills: (
        list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]]
        | None
    ) = None

    @field_validator("skills")
    @classmethod
    def validate_skills_content(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        for skill in values:
            if "\x00" in skill:
                raise ValueError("Навык не может содержать нулевой символ")
        seen = set()
        unique = []
        for s in values:
            if s.lower() not in seen:
                seen.add(s.lower())
                unique.append(s)
        return unique

    @model_validator(mode="after")
    def validate_workshift(self) -> Self:
        if (
            self.workshift_start is not None
            and self.workshift_end is not None
            and self.workshift_start == self.workshift_end
        ):
            raise ValueError("Начало и окончание рабочей смены не могут совпадать")
        return self


class UserUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [USER_UPDATE_EXAMPLE]},
    )

    name: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
        | None
    ) = None
    surname: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
        | None
    ) = None
    lastname: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
        | None
    ) = None
    username: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=50)] | None
    ) = None
    password: Annotated[str, StringConstraints(min_length=8, max_length=128)] | None = Field(
        default=None, description="Новый пароль пользователя (если требуется сменить)"
    )
    role: UserRole | None = Field(
        default=None,
        description=(
            "Роль пользователя: observer — наблюдатель, "
            "foreman — бригадир, worker — выездной специалист"
        ),
    )
    worker_profile: WorkerProfileUpdate | None = Field(
        default=None,
        description="Данные смены и навыков (актуально для роли worker)",
    )

    @field_validator("name", "surname", "lastname", "username", "password")
    @classmethod
    def reject_null_character(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("Поле не может содержать нулевой символ")
        return value

    @model_validator(mode="after")
    def validate_role_profile_coupling(self) -> Self:
        if self.role in (UserRole.OBSERVER, UserRole.FOREMAN) and self.worker_profile is not None:
            raise ValueError("Профиль worker_profile недопустим для ролей observer и foreman")
        return self

"""Work type contracts; validation mirrors the database constraints."""

from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

WorkTypeName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
# A single part of the norm longer than a day is a typo, not a real norm.
Minutes = Annotated[int, Field(strict=True, ge=0, le=1440)]
NORM_PARTS = ("travel_minutes", "work_minutes", "documents_minutes")

WORK_TYPE_EXAMPLE = {
    "id": 1,
    "name": "Подключение клиентов Базовая",
    "travel_minutes": 20,
    "work_minutes": 60,
    "documents_minutes": 10,
    "norm_minutes": 90,
}
WORK_TYPE_CREATE_EXAMPLE = {
    "name": "Монтаж СКС",
    "travel_minutes": 20,
    "work_minutes": 120,
    "documents_minutes": 15,
}
WORK_TYPE_UPDATE_EXAMPLE = {"work_minutes": 70}


def _reject_null_character(value: str | None) -> str | None:
    if value is not None and "\x00" in value:
        raise ValueError("Название вида работ не может содержать нулевой символ")
    return value


class WorkTypeRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_extra={"examples": [WORK_TYPE_EXAMPLE]}
    )

    id: int
    name: str = Field(description="Название вида работ.")
    travel_minutes: int = Field(description="Дорога до клиента или ТКД, минуты.")
    work_minutes: int = Field(description="Технические работы, минуты.")
    documents_minutes: int = Field(description="Оформление документов, минуты.")
    norm_minutes: int = Field(
        description="Базовый норматив: сумма дороги, технических работ и документов."
    )


class WorkTypeCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [WORK_TYPE_CREATE_EXAMPLE]}
    )

    name: WorkTypeName = Field(description="Уникально без учёта регистра.")
    travel_minutes: Minutes = Field(description="Дорога до клиента или ТКД, 0–1440 минут.")
    work_minutes: Minutes = Field(description="Технические работы, 0–1440 минут.")
    documents_minutes: Minutes = Field(description="Оформление документов, 0–1440 минут.")

    @field_validator("name")
    @classmethod
    def reject_null_character(cls, value: str | None) -> str | None:
        return _reject_null_character(value)

    @model_validator(mode="after")
    def norm_is_positive(self) -> Self:
        if sum(getattr(self, part) for part in NORM_PARTS) == 0:
            raise ValueError("Норматив должен быть больше нуля")
        return self


class WorkTypeUpdate(BaseModel):
    """Only the passed fields change; the norm is recalculated by the database."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [WORK_TYPE_UPDATE_EXAMPLE]}
    )

    name: WorkTypeName | None = None
    travel_minutes: Minutes | None = None
    work_minutes: Minutes | None = None
    documents_minutes: Minutes | None = None

    @field_validator("name")
    @classmethod
    def reject_null_character(cls, value: str | None) -> str | None:
        return _reject_null_character(value)

    @model_validator(mode="after")
    def has_non_null_changes(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Передайте хотя бы одно поле для изменения")
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"Поле {field} не может быть null")
        return self

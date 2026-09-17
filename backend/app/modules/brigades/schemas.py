"""Request and response schemas for brigade management."""

from typing import Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

PositiveInt32 = Annotated[int, Field(strict=True, ge=1, le=2_147_483_647)]
BrigadeName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
WorkerIds = Annotated[list[PositiveInt32], Field(max_length=100)]


class BrigadeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: BrigadeName
    foreman_id: PositiveInt32
    office_id: PositiveInt32
    worker_ids: WorkerIds = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def reject_null_character(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("Название бригады не может содержать нулевой символ")
        return value

    @field_validator("worker_ids")
    @classmethod
    def reject_duplicate_workers(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("Исполнитель не может повторяться в составе бригады")
        return value


class BrigadeMembersUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    foreman_id: PositiveInt32
    office_id: PositiveInt32
    worker_ids: WorkerIds

    @field_validator("worker_ids")
    @classmethod
    def reject_duplicate_workers(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("Исполнитель не может повторяться в составе бригады")
        return value


class BrigadeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: PositiveInt32
    name: str
    foreman_id: PositiveInt32
    office_id: PositiveInt32
    worker_ids: list[PositiveInt32]
    created_at: AwareDatetime
    updated_at: AwareDatetime

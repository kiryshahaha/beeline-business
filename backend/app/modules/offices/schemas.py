"""Request and response schemas for offices management."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

PositiveInt32 = Annotated[int, Field(strict=True, ge=1, le=2_147_483_647)]
OfficeName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]


class OfficeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: OfficeName
    location_id: PositiveInt32

    @field_validator("name")
    @classmethod
    def reject_null_character(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("Название офиса не может содержать нулевой символ")
        return value


class OfficeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: PositiveInt32
    name: str
    location_id: PositiveInt32

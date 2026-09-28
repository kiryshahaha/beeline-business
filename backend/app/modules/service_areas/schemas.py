"""Pydantic schemas for service areas."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

NonEmptyString = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
CodeString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


class ServiceAreaBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: CodeString
    name: NonEmptyString
    description: str | None = None


class ServiceAreaCreate(ServiceAreaBase):
    pass


class ServiceAreaUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: NonEmptyString | None = None
    description: str | None = None


class TerritoryIssue(BaseModel):
    code: str
    subject: str
    subject_id: int
    sources: dict[str, int | None]


class TerritoryConsistencyReport(BaseModel):
    consistent: bool
    workers: list[TerritoryIssue]
    brigades: list[TerritoryIssue]
    tickets: list[TerritoryIssue]


class ServiceAreaRead(ServiceAreaBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime

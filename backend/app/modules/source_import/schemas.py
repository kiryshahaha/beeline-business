"""HTTP DTOs of the source import; the import report itself is described in the README."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SourceImportSummary(BaseModel):
    id: int
    service_area_id: int
    service_area_code: str
    dataset: str
    kind: Literal["demand", "control"]
    filename: str
    file_sha256: str
    mapping_version: int
    work_date: date | None
    office_id: int | None
    created_by: int
    created_at: datetime
    counts: dict[str, int] | None


class SourceAddressRead(BaseModel):
    id: int
    service_area_id: int
    raw_address: str
    location_id: int
    status: Literal["unresolved", "geocoded", "ambiguous", "manual"]
    source: str | None
    confidence: Decimal | None
    candidate_latitude: Decimal | None
    candidate_longitude: Decimal | None
    latitude: Decimal | None = Field(description="Координаты адреса, которые видит планировщик.")
    longitude: Decimal | None
    reviewed_by: int | None
    updated_at: datetime


class AddressReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

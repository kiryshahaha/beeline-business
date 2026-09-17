"""Pydantic v2 schemas for appliances, stock, and ticket allocations."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.modules.appliances.enums import ApplianceType

NotBlankString150 = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=150,
    ),
]

NotBlankString20 = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=20,
    ),
]

PositiveInt = Annotated[int, Field(strict=True, ge=1, le=2_147_483_647)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0, le=2_147_483_647)]


class ApplianceBase(BaseModel):
    name: NotBlankString150
    description: str | None = None
    type: ApplianceType
    unit: NotBlankString20 = "шт"


class ApplianceCreate(ApplianceBase):
    pass


class ApplianceUpdate(BaseModel):
    name: NotBlankString150 | None = None
    description: str | None = None
    type: ApplianceType | None = None
    unit: NotBlankString20 | None = None
    is_active: bool | None = None


class ApplianceRead(ApplianceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class OfficeStockItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    office_id: int
    appliance_id: int
    name: str
    description: str | None = None
    type: ApplianceType
    unit: str
    stock: int
    reserved: int
    available: int


class OfficeStockSetRequest(BaseModel):
    stock: NonNegativeInt


class TicketApplianceCreate(BaseModel):
    appliance_id: PositiveInt
    quantity: PositiveInt
    office_id: PositiveInt | None = None


class TicketApplianceUpdate(BaseModel):
    quantity: PositiveInt


class TicketApplianceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticket_id: int
    appliance_id: int
    appliance_name: str
    appliance_type: ApplianceType
    unit: str
    office_id: int
    quantity: int
    created_at: datetime

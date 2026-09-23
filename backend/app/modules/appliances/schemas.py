"""Pydantic v2 schemas for appliances, stock, and ticket allocations."""

from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

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


# --- Units on hand, kit and inventory journal ---

OperationKey = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
KitQuantity = Annotated[int, Field(strict=True, ge=0, le=1000)]


class KitReserveSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: KitQuantity


class KitReserveItemRead(BaseModel):
    office_id: int
    appliance_id: int
    name: str
    unit: str
    quantity: int


class WorkerEquipmentItem(BaseModel):
    appliance_id: int
    name: str
    type: ApplianceType
    unit: str
    on_hand: int
    committed: int
    free: int


class KitLine(BaseModel):
    appliance_id: int
    name: str
    unit: str
    quantity: int
    office_id: int
    ticket_id: int | None
    purpose: Literal["ticket", "reserve"]


class KitShortage(BaseModel):
    office_id: int
    appliance_id: int
    stock: int
    reserved: int
    requested: int


class WorkerEquipmentRead(BaseModel):
    worker_id: int
    office_id: int | None
    date: date
    items: list[WorkerEquipmentItem]
    to_issue: list[KitLine]
    shortages: list[KitShortage]


class IssueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_key: OperationKey
    date: date


class ReturnItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    appliance_id: PositiveInt
    quantity: PositiveInt


class ReturnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_key: OperationKey
    office_id: PositiveInt | None = None
    items: list[ReturnItem] = Field(default_factory=list, max_length=100)
    ticket_ids: list[PositiveInt] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def something_to_return(self) -> Self:
        if not self.items and not self.ticket_ids:
            raise ValueError("Укажите оборудование или заявки для возврата")
        appliances = [item.appliance_id for item in self.items]
        if len(appliances) != len(set(appliances)) or len(self.ticket_ids) != len(
            set(self.ticket_ids)
        ):
            raise ValueError("Позиции и заявки не должны повторяться")
        return self


class RestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_key: OperationKey
    reason: Reason


class MovementRead(BaseModel):
    appliance_id: int
    quantity: int
    ticket_id: int | None
    from_office_id: int | None
    from_worker_id: int | None
    to_office_id: int | None
    to_worker_id: int | None


class OperationRead(BaseModel):
    id: int
    operation_key: str
    kind: Literal["issue", "return", "consume", "restore"]
    worker_id: int | None
    ticket_id: int | None
    actor_id: int | None
    reason: str | None
    recorded_at: datetime
    already_applied: bool
    movements: list[MovementRead]

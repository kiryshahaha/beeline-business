"""Ticket request/response contracts; validation mirrors the agreed database constraints."""

from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.modules.execution.enums import TicketLifecycleState
from app.modules.locations.schemas import LocationRead
from app.modules.tickets.enums import TicketCategory, TicketStatus
from app.modules.users.enums import TransportType

PositiveInt32 = Annotated[int, Field(strict=True, ge=1, le=2_147_483_647)]
NonNegativeInt32 = Annotated[int, Field(strict=True, ge=0, le=2_147_483_647)]

# Documentation examples only. IDs must be replaced with values from the user's database.
TICKET_CREATE_EXAMPLE = {
    "location_id": 1,
    "title": "Настроить Wi-Fi",
    "description": "Учебный пример заявки",
    "work_type_id": 1,
    "category": "connection",
    "priority": 2,
    "received_at": "2026-09-13T09:00:00+03:00",
    "sla_deadline_at": None,
    "required_transport_type": None,
    "status": "planned",
    "visit_window_start": "2026-09-14T10:00:00+03:00",
    "visit_window_end": "2026-09-14T14:00:00+03:00",
    "planned_start_at": None,
    "planned_end_at": None,
    "estimated_duration_minutes": 60,
    "actual_duration_minutes": None,
}

TICKET_READ_EXAMPLE = {
    **TICKET_CREATE_EXAMPLE,
    "work_type": "Настройка сети",
    "id": 1,
    "assignee_ids": [2],
    "state": "waiting_assignment",
    "revision": 1,
    "execution_cycle": 1,
    "actual_started_at": None,
    "actual_completed_at": None,
    "cancel_reason": None,
    "last_event_id": None,
    "created_at": "2026-09-13T09:00:00+03:00",
    "updated_at": "2026-09-13T09:00:00+03:00",
    "location": {
        "id": 1,
        "city_id": 1,
        "city": "Санкт-Петербург",
        "district_id": 1,
        "district": "Невский район",
        "street_id": 1,
        "street": "Искровский проспект",
        "building_id": 1,
        "building_number": "4",
        "block": "корпус 2",
        "entrance_id": 1,
        "entrance_number": "1",
        "floor": 3,
        "apartment": "12",
        "latitude": 59.9156,
        "longitude": 30.4631,
        "address": (
            "Санкт-Петербург, Невский район, Искровский проспект, д. 4, корпус 2, "
            "подъезд 1, этаж 3, кв./пом. 12"
        ),
    },
}


class TicketFields(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    location_id: PositiveInt32 = Field(
        description="ID существующего места выполнения. В примере замените 1 на ID из вашей БД."
    )
    service_area_id: PositiveInt32 | None = Field(
        default=None,
        description="ID участка обслуживания.",
    )
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    description: str | None = None
    work_type_id: PositiveInt32 | None = Field(
        default=None,
        description="ID вида работ из справочника work_types.",
    )
    category: TicketCategory | None = Field(
        default=None,
        description=(
            "Каноническая категория: emergency, connection, repair, additional. "
            "По умолчанию берётся из вида работ."
        ),
    )
    priority: PositiveInt32 | None = Field(
        default=None,
        description="Приоритет выполнения (1 — наивысший, 2 — подключение, 3 — обычные).",
    )
    received_at: AwareDatetime | None = Field(
        default=None,
        description="Время поступления заявки. По умолчанию текущее время.",
    )
    sla_deadline_at: AwareDatetime | None = Field(
        default=None,
        description="Крайний срок завершения по SLA.",
    )
    required_transport_type: TransportType | None = Field(
        default=None,
        description=(
            "Обязательный транспорт исполнителя (car, walking, bicycle, public_transport). "
            "null — любой."
        ),
    )
    status: TicketStatus = Field(
        default=TicketStatus.PLANNED,
        description="planned — запланирована, in_progress — в работе, "
        "completed — завершена, wont_fix — не будет исправлено.",
    )
    visit_window_start: AwareDatetime = Field(
        description="Начало допустимого окна визита. Обязателен часовой пояс, например +03:00."
    )
    visit_window_end: AwareDatetime = Field(
        description="Конец допустимого окна визита, строго позже его начала."
    )
    planned_start_at: AwareDatetime | None = Field(
        default=None,
        description="Запланированное начало работы; null, если время ещё не назначено.",
    )
    planned_end_at: AwareDatetime | None = Field(
        default=None,
        description="Запланированное окончание, строго позже начала. "
        "Обе плановые даты заполняются вместе либо обе остаются null.",
    )
    estimated_duration_minutes: PositiveInt32 = Field(
        description="Ожидаемая длительность работы в минутах, больше нуля."
    )
    actual_duration_minutes: NonNegativeInt32 | None = Field(
        default=None,
        description="Фактическая длительность в минутах, введённая вручную. "
        "null — ещё не указана, 0 — явно введённые ноль минут.",
    )

    @field_validator("title", "description")
    @classmethod
    def reject_null_character(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("Текст не может содержать нулевой символ")
        return value

    @model_validator(mode="after")
    def validate_intervals(self) -> Self:
        if self.visit_window_end <= self.visit_window_start:
            raise ValueError("Конец окна визита должен быть позже начала")
        if (self.planned_start_at is None) != (self.planned_end_at is None):
            raise ValueError("Плановые начало и окончание нужно передавать вместе")
        if (
            self.planned_start_at is not None
            and self.planned_end_at is not None
            and self.planned_end_at <= self.planned_start_at
        ):
            raise ValueError("Плановое окончание должно быть позже начала")
        if (
            self.sla_deadline_at is not None
            and self.received_at is not None
            and self.sla_deadline_at <= self.received_at
        ):
            raise ValueError("Срок SLA должен быть позже времени поступления")
        return self


class TicketCreate(TicketFields):
    work_type_id: PositiveInt32 = Field(
        description="ID существующего вида работ из справочника work_types."
    )
    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [TICKET_CREATE_EXAMPLE]}
    )


class TicketAssigneesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_ids: list[PositiveInt32] = Field(
        min_length=0,
        max_length=100,
        description="Полный список ID исполнителей, назначенных на заявку.",
    )

    @field_validator("worker_ids")
    @classmethod
    def remove_duplicates(cls, values: list[int]) -> list[int]:
        return list(dict.fromkeys(values))


class TicketStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TicketStatus
    expected_revision: PositiveInt32 | None = None
    reason: str | None = Field(default=None, max_length=2000)


class TicketSlaEstimateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    previous_ticket_end_at: AwareDatetime
    travel_minutes: NonNegativeInt32


class TicketSlaEstimateRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_id: PositiveInt32
    estimated_arrival_at: AwareDatetime
    estimated_service_start_at: AwareDatetime
    estimated_service_end_at: AwareDatetime
    visit_window_end_at: AwareDatetime
    arrival_status: Literal["within_window", "late"]
    arrival_late_minutes: NonNegativeInt32
    sla_deadline_at: AwareDatetime | None
    sla_status: Literal["on_time", "at_risk", "not_configured"]
    sla_late_minutes: NonNegativeInt32
    duration_minutes: PositiveInt32
    duration_source: Literal["ticket_estimate", "work_norm"]


class TicketRead(TicketFields):
    model_config = ConfigDict(json_schema_extra={"examples": [TICKET_READ_EXAMPLE]})

    id: int
    work_type: str | None = None
    work_type_id: int | None = None
    category: TicketCategory
    priority: int
    received_at: AwareDatetime
    sla_deadline_at: AwareDatetime | None = None
    required_transport_type: TransportType | None = None
    service_duration_source: str | None = None
    state: TicketLifecycleState = Field(description="Каноническое состояние выполнения заявки.")
    revision: PositiveInt32
    execution_cycle: PositiveInt32
    actual_started_at: AwareDatetime | None = None
    actual_completed_at: AwareDatetime | None = None
    cancel_reason: str | None = None
    last_event_id: PositiveInt32 | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    location: LocationRead
    assignee_ids: list[int] = Field(default_factory=list)

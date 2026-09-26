"""Timeline response: every interval is an absolute moment in Moscow time."""

import datetime as dt
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field

from app.modules.tickets.enums import TicketCategory, TicketStatus
from app.modules.users.enums import TransportType


class ShiftInterval(BaseModel):
    start: AwareDatetime
    end: AwareDatetime


class ScheduleTicket(BaseModel):
    id: int
    title: str
    work_type: str
    status: TicketStatus
    start: AwareDatetime = Field(description="Плановое начало работы по заявке.")
    end: AwareDatetime = Field(description="Плановое окончание работы по заявке.")


class ScheduleConflict(BaseModel):
    code: Literal[
        "route_outdated",
        "not_in_route",
        "route_time_mismatch",
        "visits_overlap",
        "outside_shift",
        "during_absence",
    ]
    message: str
    ticket_ids: list[int]


class ScheduleVisit(BaseModel):
    ticket_id: int
    sequence: int | None = None
    arrival: AwareDatetime | None = Field(
        default=None, description="Прибытие по сохранённому маршруту."
    )
    start: AwareDatetime
    end: AwareDatetime
    waiting_minutes: int = Field(description="Ожидание открытия окна клиента.")
    source: Literal["route", "ticket"] = Field(
        description="route — время из сохранённого маршрута; ticket — заявки нет в "
        "маршруте, показано её собственное плановое время."
    )


class ScheduleRoute(BaseModel):
    id: int
    route_number: int
    created_at: AwareDatetime
    day_revision: int | None = Field(
        default=None, description="Ревизия плана дня, с которой маршрут был применён."
    )
    is_current_plan: bool | None = Field(
        default=None,
        description="false — ревизия маршрута уже заменена; null — маршрут сохранён вне "
        "планировщика.",
    )


class ScheduleAvailability(BaseModel):
    available: bool
    unavailable_at: AwareDatetime | None = None
    unavailable_until: AwareDatetime | None = None
    expected_available_at: AwareDatetime | None = None
    reason: str | None = None


class ScheduleWorkerDay(BaseModel):
    """План исполнителя на дату в той же модели смены, что использует планировщик."""

    shift_start: AwareDatetime = Field(description="Смена этой даты; ночная кончается утром.")
    shift_end: AwareDatetime
    availability: ScheduleAvailability
    route: ScheduleRoute | None
    visits: list[ScheduleVisit]
    service_minutes: int
    travel_minutes: int
    waiting_minutes: int
    free_minutes: int
    overtime_minutes: int = Field(
        description="Время визитов за пределами смены. Политики переработки нет, "
        "поэтому это нарушение, а не допустимая загрузка."
    )
    conflicts: list[ScheduleConflict]


class ScheduleWorker(BaseModel):
    id: int
    full_name: str = Field(description="Фамилия, имя и отчество, если оно указано.")
    transport_type: TransportType
    is_on_line: bool
    workshift_start: dt.time
    workshift_end: dt.time
    shifts: list[ShiftInterval] = Field(
        description="Смены, пересекающие выбранные сутки, целиком. Ночная смена даёт "
        "две записи: вчерашнюю, которая заканчивается утром, и сегодняшнюю."
    )
    tickets: list[ScheduleTicket] = Field(
        description="Назначенные заявки, плановый интервал которых пересекает сутки."
    )
    day_plan: ScheduleWorkerDay = Field(
        description="Смена даты, доступность, маршрут, дорога, ожидание и конфликты."
    )


class ScheduleForeman(BaseModel):
    id: int
    full_name: str


class ScheduleBrigade(BaseModel):
    id: int
    name: str
    office_id: int
    office_name: str
    foreman: ScheduleForeman
    workers: list[ScheduleWorker]


class ScheduleUnassignedTicket(BaseModel):
    id: int
    title: str
    work_type: str | None
    category: TicketCategory
    priority: int
    service_area_id: int | None
    visit_window_start: AwareDatetime
    visit_window_end: AwareDatetime
    sla_deadline_at: AwareDatetime | None = None


class SchedulePlanRevision(BaseModel):
    service_area_id: int
    current_revision: int | None = Field(
        description="Текущая ревизия плана участка на дату; null — план не применялся."
    )


class ScheduleRead(BaseModel):
    date: dt.date
    office_id: int | None
    day_start: AwareDatetime = Field(description="Начало суток по Москве.")
    day_end: AwareDatetime = Field(description="Конец суток по Москве, не включается.")
    brigades: list[ScheduleBrigade]
    unassigned_workers: list[ScheduleWorker] = Field(
        description="Исполнители без бригады. Заполняется только для наблюдателя "
        "без фильтра office_id: без бригады у исполнителя нет офиса."
    )
    unassigned_tickets: list[ScheduleUnassignedTicket] = Field(
        description="Открытые заявки без исполнителя, окно которых пересекает сутки, "
        "в участках видимых офисов."
    )
    plan_revisions: list[SchedulePlanRevision] = Field(
        description="Текущая ревизия плана дня для каждого видимого участка."
    )

"""Timeline response: every interval is an absolute moment in Moscow time."""

import datetime as dt

from pydantic import AwareDatetime, BaseModel, Field

from app.modules.tickets.enums import TicketStatus
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

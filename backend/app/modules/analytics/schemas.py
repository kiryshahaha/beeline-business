"""Schemas for analytics query parameters and responses."""

from datetime import date
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.modules.execution.enums import TicketLifecycleState
from app.modules.tickets.enums import TicketCategory, TicketStatus
from app.modules.users.enums import UserRole


class AnalyticsPeriod(StrEnum):
    TODAY = "today"
    WEEK = "week"
    MONTH = "month"


class TicketsSummary(BaseModel):
    """Four different questions, deliberately not one number.

    The current state does not depend on the period: a ticket opened last month is still
    open today and must not disappear from the board when the period is `today`.
    """

    model_config = ConfigDict(extra="forbid")

    period_start: AwareDatetime = Field(description="Начало периода по Москве, включается.")
    period_end: AwareDatetime = Field(description="Конец периода по Москве, не включается.")
    plan_date: date = Field(description="Дата, на которую считается план.")
    open: int = Field(description="Сейчас: planned без исполнителя.")
    open_unassigned: int = Field(description="То же число под явным именем.")
    open_assigned: int = Field(description="Сейчас: planned с исполнителем.")
    assigned: int = Field(description="Синоним open_assigned для существующих клиентов.")
    in_progress: int = Field(description="Сейчас: работа идёт.")
    created_in_period: int = Field(description="Созданы внутри периода.")
    completed_in_period: int = Field(
        description="Завершены внутри периода по фактическому времени завершения. "
        "updated_at не используется: правка закрытой заявки не считается завершением."
    )
    completed: int = Field(description="Синоним completed_in_period для существующих клиентов.")
    planned_for_date: int = Field(description="Визиты, обещанные на plan_date.")


class FastStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sla_compliance_percent: int
    at_risk_tickets_count: int
    average_delay_minutes: int
    idle_workers_count: int
    at_risk_tickets_ids: list[int]
    idle_workers_ids: list[int]
    active_brigades_count: int


class BrigadeWorkloadItem(BaseModel):
    """Загрузка по сменам даты, а не число всех активных строк в базе."""

    model_config = ConfigDict(extra="forbid")

    brigade_id: int
    brigade_name: str
    date: date
    workers: int
    available_workers: int = Field(
        description="Без отметки о недоступности на эту дату; только их смены дают ёмкость."
    )
    tickets: int = Field(description="Визиты этой даты у исполнителей бригады.")
    shift_minutes: int = Field(description="Сумма смен доступных исполнителей на эту дату.")
    service_minutes: int
    travel_minutes: int = Field(description="Дорога по сохранённым маршрутам дня.")
    waiting_minutes: int = Field(description="Ожидание открытия окна клиента.")
    free_minutes: int = Field(description="Часть смен, не занятая визитами, дорогой и ожиданием.")
    overtime_minutes: int = Field(
        description="Визиты за пределами смены. Политики переработки нет, поэтому это "
        "нарушение плана, а не дополнительная ёмкость."
    )
    conflicts: int = Field(description="Число конфликтов расписания у исполнителей бригады.")
    active_tickets: int = Field(description="Синоним tickets для существующих клиентов.")
    completed_today: int = Field(description="Завершены за эти сутки по факту.")


class ActivityKind(StrEnum):
    TICKET_CREATED = "ticket_created"
    TICKET_ASSIGNED = "ticket_assigned"
    TICKET_REASSIGNED = "ticket_reassigned"
    TICKET_UNASSIGNED = "ticket_unassigned"
    PLAN_APPLIED = "plan_applied"
    TICKET_STATUS_CHANGED = "ticket_status_changed"
    TICKET_CANCELLED = "ticket_cancelled"
    TICKET_RESCHEDULED = "ticket_rescheduled"
    TICKET_DELAYED = "ticket_delayed"
    WORKER_REDIRECTED = "worker_redirected"
    COMMENT_ADDED = "comment_added"
    COMMENT_EDITED = "comment_edited"


class AssignmentSource(StrEnum):
    MANUAL = "manual"
    PLAN = "plan"
    LINE_STATUS = "line_status"
    DIRECT = "direct"
    BACKFILL = "backfill"


class ActivityPerson(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    full_name: str
    role: UserRole


class ActivityTicket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    title: str
    work_type_id: int | None = None
    work_type: str | None = None
    category: TicketCategory
    priority: int
    received_at: AwareDatetime
    sla_deadline_at: AwareDatetime | None = None
    status: TicketStatus = Field(
        description="Текущий статус заявки, а не статус на момент события."
    )


class ActivityDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    previous_status: TicketStatus | None = None
    status: TicketStatus | None = Field(default=None, description="Статус после события.")
    previous_state: TicketLifecycleState | None = None
    state: TicketLifecycleState | None = Field(
        default=None, description="Этап жизненного цикла после события."
    )
    worker: ActivityPerson | None = Field(default=None, description="Новый исполнитель.")
    previous_worker: ActivityPerson | None = Field(
        default=None, description="Исполнитель до переназначения или снятия."
    )
    assignment_source: AssignmentSource | None = Field(
        default=None,
        description="Путь изменения: ручное назначение, план, снятие с линии и т. д.",
    )
    reason: str | None = Field(default=None, description="Причина, записанная автором события.")
    comment_id: int | None = None
    comment_excerpt: str | None = Field(
        default=None,
        description="Начало текущего текста комментария; длинный текст обрезается "
        "многоточием. Прежние редакции не хранятся: у события правки это сегодняшний "
        "текст, а не тот, что был в момент правки.",
    )


class ActivityItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ActivityKind
    occurred_at: AwareDatetime
    ticket: ActivityTicket
    actor: ActivityPerson | None = Field(
        default=None, description="Кто выполнил действие; null, если система его не записала."
    )
    details: ActivityDetails

"""Plan report: route order, times, workers, categories, reasons and totals of one plan.

It is a separate file, not a variant of the ticket export: rows come from the stored plan,
and ticket fields from the input snapshot the plan was calculated with.
"""

from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.planning import service as planning_service
from app.modules.planning.errors import PlanningError
from app.modules.planning.models import PlanningPlan
from app.modules.planning.schemas import Explanation, PlanRead
from app.modules.reports import repository
from app.modules.reports.errors import ReportError
from app.modules.reports.tables import (
    XLSX_MEDIA_TYPE,
    ZIP_MEDIA_TYPE,
    CellTooLongError,
    ExportFile,
    Table,
    build_file,
    write_csv_zip,
    write_xlsx,
)

MOSCOW = ZoneInfo("Europe/Moscow")

SUMMARY_COLUMNS = ("field", "label", "value")
ROUTE_COLUMNS = (
    "worker_id",
    "worker",
    "route_number",
    "transport_type",
    "routing_mode",
    "departure_at",
    "return_at",
    "visits",
    "distance_meters",
    "travel_minutes",
    "service_minutes",
    "waiting_minutes",
)
VISIT_COLUMNS = (
    "worker_id",
    "worker",
    "sequence",
    "ticket_id",
    "title",
    "work_type",
    "category",
    "priority",
    "visit_window_start",
    "visit_window_end",
    "arrival_at",
    "service_start_at",
    "service_end_at",
    "waiting_minutes",
    "service_minutes",
    "duration_source",
    "factors",
)
UNASSIGNED_COLUMNS = (
    "ticket_id",
    "title",
    "work_type",
    "category",
    "priority",
    "visit_window_start",
    "visit_window_end",
    "reason_code",
    "reason_category",
    "reason",
    "candidates",
)
EXCLUDED_COLUMNS = ("worker_id", "worker", "reason_code", "reason_category", "reason")

METRIC_LABELS = (
    ("requested_tickets", "Заявок в расчёте"),
    ("eligible_tickets", "Допущено к расчёту"),
    ("assigned_tickets", "Назначено заявок"),
    ("unassigned_tickets", "Не назначено заявок"),
    ("requested_workers", "Инженеров в расчёте"),
    ("available_workers", "Доступно инженеров"),
    ("used_workers", "Задействовано инженеров"),
    ("distance_meters", "Расстояние, м"),
    ("travel_minutes", "В пути, мин"),
    ("service_minutes", "Работа, мин"),
    ("waiting_minutes", "Ожидание, мин"),
)


def _moscow(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.astimezone(MOSCOW).isoformat()


def _messages(reasons: list[Explanation]) -> str:
    return "; ".join(reason.message for reason in reasons)


class _Context:
    """Ticket fields as the plan saw them, and current display names of workers."""

    def __init__(self, plan: PlanningPlan, names: dict[int, str]):
        snapshot = plan.input_snapshot
        self.tickets = {row["id"]: row for row in snapshot.get("tickets", [])}
        self.work_types = {row["id"]: row["name"] for row in snapshot.get("work_types", [])}
        self.names = names

    def ticket(self, ticket_id: int) -> list[Any]:
        row = self.tickets.get(ticket_id, {})
        work_type = self.work_types.get(row.get("work_type_id"), row.get("work_type"))
        return [
            row.get("title"),
            work_type,
            row.get("category"),
            row.get("priority"),
            _moscow(row.get("visit_window_start")),
            _moscow(row.get("visit_window_end")),
        ]


def _summary(plan: PlanRead, stored: PlanningPlan) -> list[list[Any]]:
    policy = plan.planning_policy
    rows = [
        ["plan_id", "План", str(plan.plan_id)],
        ["state", "Состояние", plan.state],
        ["outcome", "Результат расчёта", plan.outcome],
        ["is_current", "Совпадает с текущими данными", plan.is_current],
        ["route_date", "Дата маршрутов", plan.route_date],
        ["service_area_id", "Район", plan.service_area_id],
        ["day_revision", "Ревизия дня", plan.day_revision],
        ["timezone", "Часовой пояс", plan.timezone],
        ["created_at", "Рассчитан", _moscow(stored.created_at)],
        ["expires_at", "Предложение действует до", _moscow(plan.expires_at)],
        ["applied_at", "Применён", _moscow(stored.applied_at)],
        ["solver_status", "Статус решателя", plan.solver_status],
        ["policy_version", "Версия политики", policy.policy_version if policy else None],
        [
            "objective_order",
            "Порядок целей",
            " > ".join(policy.objective_order) if policy else None,
        ],
        ["priority_policy", "Приоритеты", policy.priority if policy else None],
    ]
    if plan.metrics is not None:
        rows += [
            [f"metrics.{name}", label, getattr(plan.metrics, name)] for name, label in METRIC_LABELS
        ]
        rows += [
            [f"unassigned_by_category.{category}", f"Не назначено: {category}", count]
            for category, count in sorted(plan.metrics.unassigned_by_category.items())
        ]
    if plan.resource_estimate is not None:
        estimate = plan.resource_estimate
        rows += [
            [
                "resource_estimate.additional_workers",
                "Оценка: дополнительных инженеров",
                estimate.additional_workers,
            ],
            ["resource_estimate.complete", "Оценка покрывает все заявки", estimate.complete],
            ["resource_estimate.message", "Оценка", estimate.message],
        ]
    rows.append(["warnings", "Предупреждения", ", ".join(plan.warnings)])
    return rows


def _tables(plan: PlanRead, stored: PlanningPlan, context: _Context) -> list[Table]:
    numbers = {}
    if plan.apply_result is not None:
        numbers = {route.worker_id: route.route_number for route in plan.apply_result.routes}
    names = context.names
    routes = [
        [
            route.worker_id,
            names.get(route.worker_id),
            numbers.get(route.worker_id),
            route.transport_type,
            route.routing_mode,
            _moscow(route.departure_at),
            _moscow(route.return_at),
            len(route.stops),
            route.distance_meters,
            route.travel_minutes,
            route.service_minutes,
            route.waiting_minutes,
        ]
        for route in plan.routes
    ]
    visits = []
    for route in plan.routes:
        for stop in sorted(route.stops, key=lambda item: item.sequence):
            title, work_type, category, priority, window_start, window_end = context.ticket(
                stop.ticket_id
            )
            visits.append(
                [
                    route.worker_id,
                    names.get(route.worker_id),
                    stop.sequence,
                    stop.ticket_id,
                    title,
                    work_type,
                    category,
                    priority,
                    window_start,
                    window_end,
                    _moscow(stop.arrival_at),
                    _moscow(stop.service_start_at),
                    _moscow(stop.service_end_at),
                    stop.waiting_minutes,
                    stop.effective_service_minutes,
                    stop.duration_source,
                    _messages(stop.factors),
                ]
            )
    unassigned = [
        [
            item.ticket_id,
            *context.ticket(item.ticket_id),
            item.reason.code,
            item.reason.category,
            item.reason.message,
            "; ".join(
                f"{candidate.worker_id} {names.get(candidate.worker_id, '')}".rstrip()
                + f": {candidate.reason.message}"
                for candidate in item.candidates
            ),
        ]
        for item in plan.unassigned
    ]
    excluded = [
        [
            item.worker_id,
            names.get(item.worker_id),
            item.reason.code,
            item.reason.category,
            item.reason.message,
        ]
        for item in plan.excluded_workers
    ]
    return [
        Table("summary", SUMMARY_COLUMNS, _summary(plan, stored)),
        Table("routes", ROUTE_COLUMNS, routes),
        Table("visits", VISIT_COLUMNS, visits),
        Table("unassigned", UNASSIGNED_COLUMNS, unassigned),
        Table("excluded_workers", EXCLUDED_COLUMNS, excluded),
    ]


def export_plan(session: Session, plan_id: UUID, *, format: str, clock) -> ExportFile:
    with session.begin():
        # One snapshot: is_current compares the saved input with the database at this moment.
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        stored = session.get(PlanningPlan, plan_id)
        if stored is None:
            raise ReportError(404, "plan_not_found", "План не найден")
        try:
            plan = PlanRead.model_validate(planning_service.plan_state(session, stored, clock))
        except PlanningError as error:
            raise ReportError(
                error.status,
                error.code,
                "Не удалось сверить план с текущими данными",
                **error.details,
            ) from error
        worker_ids = (
            {route.worker_id for route in plan.routes}
            | {item.worker_id for item in plan.excluded_workers}
            | {candidate.worker_id for item in plan.unassigned for candidate in item.candidates}
        )
        tables = _tables(
            plan, stored, _Context(stored, repository.worker_names(session, worker_ids))
        )

    try:
        if format == "csv":
            return build_file(
                lambda file: write_csv_zip(file, tables), ZIP_MEDIA_TYPE, f"plan-{plan_id}.zip"
            )
        return build_file(
            lambda file: write_xlsx(file, tables), XLSX_MEDIA_TYPE, f"plan-{plan_id}.xlsx"
        )
    except CellTooLongError as error:
        raise ReportError(
            422,
            "xlsx_cell_too_long",
            f"Текст {error.sheet}.{error.column} длиннее лимита ячейки XLSX; выгрузите CSV",
            sheet=error.sheet,
            column=error.column,
            length=error.length,
        ) from error

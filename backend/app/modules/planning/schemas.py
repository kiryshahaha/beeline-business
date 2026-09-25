"""Public planning DTOs; matrices and database snapshots stay private."""

from datetime import date, datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.planning.case_policy import CasePolicy
from app.modules.planning.policy import ExecutionPolicy
from app.modules.routing.schemas import MultiLineString, RouteLeg
from app.modules.users.schemas import PositiveInt32


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_date: date
    service_area_id: PositiveInt32 | None = None
    base_day_revision: PositiveInt32 | None = None
    route_end: Literal["open", "return_to_start", "specific_finish"] | None = None
    ticket_ids: list[PositiveInt32] = Field(min_length=1, max_length=50)
    worker_ids: list[PositiveInt32] = Field(min_length=1, max_length=20)
    allow_partial: bool = Field(default=True, strict=True)

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        for values in (self.ticket_ids, self.worker_ids):
            if len(values) != len(set(values)):
                raise ValueError("Списки ID не должны содержать повторов")
            values.sort()
        return self


# Public DTOs deliberately omit raw snapshots, solver matrices and internal IDs.


ReasonCategory = Literal[
    "data",
    "ticket_state",
    "availability",
    "skill",
    "area",
    "transport",
    "inventory",
    "unreachable",
    "time",
    "capacity",
    "search",
    "mixed",
    "policy",
    "selection",
    "sla",
]


class Explanation(BaseModel):
    """One checked fact: why something was rejected, or why a visit is allowed."""

    code: str
    category: ReasonCategory
    message: str
    constraint: str | None
    ids: dict[str, list[int]]
    observed: dict[str, Any] | None
    required: dict[str, Any] | None


class CandidateRejection(BaseModel):
    worker_id: int
    reason: Explanation


class Rejection(BaseModel):
    ticket_id: int
    reason: Explanation
    candidates: list[CandidateRejection]


class ExcludedWorker(BaseModel):
    worker_id: int
    reason: Explanation


class PlanMetrics(BaseModel):
    requested_tickets: int
    eligible_tickets: int
    assigned_tickets: int
    unassigned_tickets: int
    requested_workers: int
    available_workers: int
    used_workers: int
    distance_meters: float
    travel_minutes: int
    service_minutes: int
    waiting_minutes: int
    unassigned_by_category: dict[ReasonCategory, int]
    routing: dict[str, Any] | None = None


class WorkerCopyEstimate(BaseModel):
    like_worker_id: int
    ticket_ids: list[int]
    travel_minutes: int


class ResourceEstimate(BaseModel):
    is_estimate: Literal[True]
    method: Literal["greedy_insertion_with_worker_copies"]
    complete: bool
    message: str
    additional_workers: int
    considered_ticket_ids: list[int]
    covered_ticket_ids: list[int]
    uncovered_ticket_ids: list[int]
    workers: list[WorkerCopyEstimate]


class PlannedVisit(BaseModel):
    ticket_id: int
    location_id: int
    sequence: int
    arrival_at: datetime
    service_start_at: datetime
    service_end_at: datetime
    waiting_minutes: int
    effective_service_minutes: int
    duration_source: Literal["ticket_estimate", "work_norm"]
    factors: list[Explanation] = []


class PlannedRoute(BaseModel):
    worker_id: int
    transport_type: str
    routing_mode: str
    start_location_id: int
    end_location_id: int
    departure_at: datetime
    return_at: datetime
    distance_meters: float
    travel_minutes: int
    service_minutes: int
    waiting_minutes: int
    stops: list[PlannedVisit]
    geometry: MultiLineString | None
    legs: list[RouteLeg]


class AppliedRoute(BaseModel):
    id: int
    worker_id: int
    route_number: int


class ApplyResult(BaseModel):
    plan_id: UUID
    state: Literal["applied"]
    already_applied: bool
    routes: list[AppliedRoute]
    assigned_ticket_ids: list[int]
    day_revision: int | None = None


class PlanWorker(BaseModel):
    """Engineer of a stored plan: affiliation when calculated, identity and state now."""

    worker_id: int
    full_name: str | None
    brigade_id: int | None
    brigade_name: str | None
    office_id: int | None
    role: str | None
    archived_at: datetime | None


class PlanRead(BaseModel):
    planning_policy: ExecutionPolicy | None = None
    case_policy_version: int | None = None
    plan_id: UUID
    state: Literal["ready", "applied", "expired", "stale"]
    outcome: Literal["complete", "partial", "empty"]
    route_date: date
    service_area_id: int | None = None
    day_revision: int | None = None
    timezone: Literal["Europe/Moscow"]
    expires_at: datetime
    solver_status: Literal["FEASIBLE", "OPTIMAL"] | None
    objective_components: dict[str, int] | None = None
    metrics: PlanMetrics | None = None
    routes: list[PlannedRoute]
    unassigned: list[Rejection]
    excluded_workers: list[ExcludedWorker]
    resource_estimate: ResourceEstimate | None = None
    warnings: list[str]
    is_current: bool | None = None
    apply_result: ApplyResult | None = None
    workers: list[PlanWorker] | None = None


class ApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PolicyRead(BaseModel):
    execution: ExecutionPolicy
    case_contract: CasePolicy


class VisitPlacement(BaseModel):
    """One promised visit as a revision published it."""

    ticket_id: int
    worker_id: int | None = None
    route_id: int | None = None
    sequence: int | None = None
    arrival_at: datetime | None = None
    service_start_at: datetime | None = None
    service_end_at: datetime | None = None


class FieldChange(BaseModel):
    previous: Any = Field(alias="from")
    current: Any = Field(alias="to")

    model_config = ConfigDict(populate_by_name=True)


class VisitChange(BaseModel):
    ticket_id: int
    changes: dict[str, FieldChange]


class MetricChange(FieldChange):
    delta: float | None = None


class DayPlanDiff(BaseModel):
    """What changed between two published revisions of the same area-day."""

    service_area_id: int
    route_date: date
    from_revision: int | None
    to_revision: int
    reason: str
    is_current: bool
    added: list[VisitPlacement]
    removed: list[VisitPlacement]
    changed: list[VisitChange]
    unchanged_ticket_ids: list[int]
    metrics: dict[str, MetricChange]


class DayPlanRevisionRead(BaseModel):
    """A published revision: who changed the day, why, and whether it still holds."""

    service_area_id: int
    route_date: date
    revision: int
    previous_revision: int | None
    superseded_by_revision: int | None
    superseded_at: datetime | None
    is_current: bool
    reason: str
    plan_id: UUID | None
    event_id: int | None
    actor_id: int
    fingerprint: str
    effective_at: datetime
    created_at: datetime
    metrics: dict[str, Any]


class DayPlanRevisionDetail(DayPlanRevisionRead):
    visits: list[VisitPlacement]
    unassigned_ticket_ids: list[int]
    diff: dict[str, Any]

"""Public planning DTOs; matrices and database snapshots stay private."""

from datetime import date, datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.planning.case_policy import CasePolicy
from app.modules.planning.policy import ExecutionPolicy
from app.modules.routing.schemas import MultiLineString, RouteLeg
from app.modules.users.schemas import PositiveInt32


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_date: date
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


class Rejection(BaseModel):
    ticket_id: int
    reason: str


class ExcludedWorker(BaseModel):
    worker_id: int
    reason: str


class PlannedVisit(BaseModel):
    ticket_id: int
    location_id: int
    sequence: int
    arrival_at: datetime
    service_end_at: datetime
    effective_service_minutes: int
    duration_source: Literal["ticket_estimate", "work_norm"]


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


class PlanRead(BaseModel):
    planning_policy: ExecutionPolicy | None = None
    plan_id: UUID
    state: Literal["ready", "applied", "expired", "stale"]
    route_date: date
    timezone: Literal["Europe/Moscow"]
    expires_at: datetime
    solver_status: Literal["FEASIBLE", "OPTIMAL"]
    routes: list[PlannedRoute]
    unassigned: list[Rejection]
    excluded_workers: list[ExcludedWorker]
    warnings: list[str]
    is_current: bool | None = None
    apply_result: ApplyResult | None = None


class ApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PolicyRead(BaseModel):
    execution: ExecutionPolicy
    case_contract: CasePolicy

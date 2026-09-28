"""Versioned execution rules for the existing solver, persisted with each proposal.

Only implemented rules belong here. The case requirements and their reference
objective live in case_policy.py; they are not advertised as solver capabilities.
Version 2 executes the case objective order in OR-Tools. Version 1 is kept only so
proposals saved before it can still be read, checked and applied as they were.
"""

import math
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.planning.errors import PlanningError
from app.modules.planning.solver_contract import OBJECTIVE_ORDER


class _ExecutionRules(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timezone: Literal["Europe/Moscow"] = "Europe/Moscow"
    visit_window: Literal["service_start_in_window", "whole_service"] = "service_start_in_window"
    window_end_inclusive: Literal[True] = True
    service_duration: Literal["configured_estimate_or_work_plus_documents"] = (
        "configured_estimate_or_work_plus_documents"
    )
    travel: Literal["provider_minutes_rounded_up_no_norm_floor"] = (
        "provider_minutes_rounded_up_no_norm_floor"
    )
    route_end: Literal["return_to_brigade_office", "open_end"] = "open_end"
    shift_end: Literal["hard_including_return"] = "hard_including_return"
    eligible_tickets: Literal["unassigned_planned"] = "unassigned_planned"
    eligible_workers: Literal["unstarted_shift_without_overlapping_assignment"] = (
        "unstarted_shift_without_overlapping_assignment"
    )
    territory: Literal["allocation_office_only_no_service_area"] = (
        "allocation_office_only_no_service_area"
    )
    equipment: Literal["office_stock_and_ticket_reservations"] = (
        "office_stock_and_ticket_reservations"
    )
    emergency_sla: Literal["service_completion_before_deadline", "not_modeled"] = (
        "service_completion_before_deadline"
    )
    ticket_transport_requirement: Literal["not_modeled"] = "not_modeled"
    manual_assignment_constraints: Literal["not_shared_with_planning"] = "not_shared_with_planning"
    search_time_limit_seconds: int = Field(default=5, strict=True, ge=1, le=10)

    def start_window(
        self, start: datetime, end: datetime, epoch: datetime, duration: int, horizon: int
    ) -> list[int]:
        """Return the allowed service-start interval [lower, upper] in minutes from epoch.

        Semantics (service_start_in_window):
          lower = ceil(window_start)  rounded UP to preserve feasibility
          upper = floor(window_end)   rounded DOWN to preserve feasibility
        Duration is NOT subtracted from upper here; instead eligibility.py checks
        that service_start + duration <= shift_end for each worker candidate.
        Rounding direction is intentional: lower up keeps the window inclusive,
        upper down keeps it inclusive on the end — both guarantee the solver
        cannot schedule outside the client's promised window.
        """
        lower = max(0, math.ceil((start - epoch).total_seconds() / 60))
        upper = min(horizon, math.floor((end - epoch).total_seconds() / 60))
        return [lower, upper]


class ExecutionPolicyV1(_ExecutionRules):
    """Rules recorded by proposals before policy version 2; never used for a new one."""

    policy_version: Literal[1] = 1
    priority: Literal["category_and_numeric_priority_penalties", "equal_ticket_penalties"] = (
        "category_and_numeric_priority_penalties"
    )
    objective_order: tuple[Literal["unassigned_total"], Literal["travel_minutes"]] = (
        "unassigned_total",
        "travel_minutes",
    )
    drop_penalty: Literal["vehicle_count_times_horizon_plus_one"] = (
        "vehicle_count_times_horizon_plus_one"
    )
    vehicle_fixed_cost: Literal[0] = 0


ObjectiveName = Literal[OBJECTIVE_ORDER]


class ExecutionPolicy(_ExecutionRules):
    """Current rules: the T01 objective order executed by the single OR-Tools solver.

    Weights are derived per problem from proven upper bounds of the lower components,
    so their sum ranks plans lexicographically. The search stays heuristic.
    """

    policy_version: Literal[2] = 2
    # Version 1 recorded these two before T03 and T02 enforced them in eligibility.
    territory: Literal["service_area_then_allocation_office"] = (
        "service_area_then_allocation_office"
    )
    ticket_transport_requirement: Literal["required_transport_type_is_hard"] = (
        "required_transport_type_is_hard"
    )
    priority: Literal["emergency_then_connection_then_repair_or_additional"] = (
        "emergency_then_connection_then_repair_or_additional"
    )
    objective_order: tuple[ObjectiveName, ...] = OBJECTIVE_ORDER
    objective_method: Literal["lexicographic_bounded_weights"] = "lexicographic_bounded_weights"
    emergency_response: Literal["minutes_from_received_to_service_start"] = (
        "minutes_from_received_to_service_start"
    )
    active_worker: Literal["route_with_at_least_one_visit"] = "route_with_at_least_one_visit"
    reassigned_visit: Literal["other_worker_than_current_assignment"] = (
        "other_worker_than_current_assignment"
    )
    search: Literal["guided_local_search_time_limited_not_proven_optimal"] = (
        "guided_local_search_time_limited_not_proven_optimal"
    )

    @model_validator(mode="after")
    def fixed_objective_order(self):
        if self.objective_order != OBJECTIVE_ORDER:
            raise ValueError("Changing the objective order requires a new policy version")
        return self


RecordedPolicy = Annotated[
    ExecutionPolicyV1 | ExecutionPolicy, Field(discriminator="policy_version")
]
POLICIES = {1: ExecutionPolicyV1, 2: ExecutionPolicy}


def execution_policy(settings=None) -> ExecutionPolicy:
    open_end = getattr(settings, "planning_open_end", True) if settings else True
    return ExecutionPolicy(
        visit_window="service_start_in_window",
        route_end="open_end" if open_end else "return_to_brigade_office",
        search_time_limit_seconds=settings.planning_solve_time_limit_seconds if settings else 5,
    )


def policy_snapshot(policy: ExecutionPolicy) -> dict:
    return {
        "policy_version": policy.policy_version,
        "planning_policy": policy.model_dump(mode="json"),
    }


def snapshot_policy(snapshot: dict) -> ExecutionPolicyV1 | ExecutionPolicy:
    """Reject unsupported execution rules before they can affect a new write.

    Pre-T01 snapshots have version 1 but no parameters. Their execution semantics
    are known, while their search limit was not recorded here. Do not backfill history.
    """
    try:
        version = snapshot.get("policy_version")
        model = POLICIES.get(version) if type(version) is int else None
        if model is None:
            raise ValueError("unsupported policy version")
        raw = snapshot.get("planning_policy")
        if "planning_policy" in snapshot and (
            not isinstance(raw, dict) or set(raw) != set(model.model_fields)
        ):
            raise ValueError("incomplete execution policy snapshot")
        if raw is None and model is not ExecutionPolicyV1:
            raise ValueError("only version 1 snapshots may omit their parameters")
        return model.model_validate(raw) if raw is not None else model()
    except ValueError as error:
        raise PlanningError("planning_policy_unsupported", 409) from error

"""Versioned execution rules for the existing solver, persisted with each proposal.

Only implemented rules belong here. The case requirements and their reference
objective live in case_policy.py; they are not advertised as solver capabilities.
"""

import math
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.planning.errors import PlanningError


class ExecutionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: Literal[1] = 1
    timezone: Literal["Europe/Moscow"] = "Europe/Moscow"
    visit_window: Literal["service_start_in_window", "whole_service"] = "service_start_in_window"
    window_end_inclusive: Literal[True] = True
    service_duration: Literal["configured_estimate_or_work_plus_documents"] = (
        "configured_estimate_or_work_plus_documents"
    )
    travel: Literal["provider_minutes_rounded_up_no_norm_floor"] = (
        "provider_minutes_rounded_up_no_norm_floor"
    )
    route_end: Literal["return_to_brigade_office", "open_end"] = "return_to_brigade_office"
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
    priority: Literal["category_and_numeric_priority_penalties", "equal_ticket_penalties"] = (
        "category_and_numeric_priority_penalties"
    )
    emergency_sla: Literal["service_completion_before_deadline", "not_modeled"] = (
        "service_completion_before_deadline"
    )
    ticket_transport_requirement: Literal["not_modeled"] = "not_modeled"
    manual_assignment_constraints: Literal["not_shared_with_planning"] = "not_shared_with_planning"
    objective_order: tuple[Literal["unassigned_total"], Literal["travel_minutes"]] = (
        "unassigned_total",
        "travel_minutes",
    )
    drop_penalty: Literal["vehicle_count_times_horizon_plus_one"] = (
        "vehicle_count_times_horizon_plus_one"
    )
    vehicle_fixed_cost: Literal[0] = 0
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

    def penalty(self, vehicles: int, horizon: int) -> int:
        return vehicles * horizon + 1


def execution_policy(settings=None) -> ExecutionPolicy:
    open_end = getattr(settings, "planning_open_end", False) if settings else False
    return ExecutionPolicy(
        visit_window="service_start_in_window",
        route_end="open_end" if open_end else "return_to_brigade_office",
        search_time_limit_seconds=settings.planning_solve_time_limit_seconds if settings else 5,
    )


def snapshot_policy(snapshot: dict) -> ExecutionPolicy:
    """Reject unsupported execution rules before they can affect a new write.

    Pre-T01 snapshots have version 1 but no parameters. Their execution semantics
    are known, while their search limit was not recorded here. Do not backfill history.
    """
    try:
        if type(snapshot.get("policy_version")) is not int or snapshot["policy_version"] != 1:
            raise ValueError("unsupported policy version")
        raw = snapshot.get("planning_policy")
        if "planning_policy" in snapshot and (
            not isinstance(raw, dict) or set(raw) != set(ExecutionPolicy.model_fields)
        ):
            raise ValueError("incomplete execution policy snapshot")
        return ExecutionPolicy.model_validate(raw) if raw is not None else ExecutionPolicy()
    except ValueError as error:
        raise PlanningError("planning_policy_unsupported", 409) from error

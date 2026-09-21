"""Validated case contract and reference comparison, not a second planner.

This defines T01 decisions for the subsequent domain/solver changes. The current
execution policy remains explicitly separate until those changes are implemented.
"""

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NonNegative = Annotated[int, Field(strict=True, ge=0)]
OBJECTIVES = (
    "unassigned_emergencies",
    "emergency_response_minutes",
    "unassigned_connections",
    "unassigned_total",
    "active_workers",
    "travel_minutes",
    "changed_future_visits",
)


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CaseRule(ContractModel):
    id: str
    origin: Literal["confirmed", "team_decision"]
    sources: tuple[str, ...] = Field(min_length=1)
    acceptance: tuple[str, ...] = Field(min_length=1)
    implementation_tasks: tuple[str, ...] = Field(min_length=1)
    statement: str = Field(min_length=1)


class CasePolicy(ContractModel):
    policy_id: Literal["beeline_case"]
    policy_version: Literal[1]
    activation: Literal["contract_only"]
    objective_order: tuple[str, ...]
    rules: tuple[CaseRule, ...]

    @model_validator(mode="after")
    def validate_contract(self):
        if self.objective_order != OBJECTIVES:
            raise ValueError("Changing the objective hierarchy requires a new case policy version")
        ids = [r.id for r in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate rule id")
        covered = {a for r in self.rules for a in r.acceptance}
        if not {f"A{i:02}" for i in range(1, 19)} <= covered:
            raise ValueError("Case policy must trace every A01-A18 acceptance scenario")
        return self


class ObjectiveMetrics(ContractModel):
    """Counts for one candidate on the SAME demand, time and frozen-prefix scope.

    Empty routes do not count as active workers. Response delay is summed only
    for served emergencies: service_start - received_at, rounded up to minutes.
    A hard violation excludes a candidate instead of becoming a soft penalty.
    """

    hard_violations: NonNegative = 0
    unassigned_emergencies: NonNegative
    emergency_response_minutes: NonNegative
    unassigned_connections: NonNegative
    unassigned_total: NonNegative
    active_workers: NonNegative
    travel_minutes: NonNegative
    changed_future_visits: NonNegative

    @model_validator(mode="after")
    def consistent_counts(self):
        if self.unassigned_emergencies + self.unassigned_connections > self.unassigned_total:
            raise ValueError("Unassigned category counts exceed total")
        return self


def objective_key(metrics: ObjectiveMetrics) -> tuple[int, ...]:
    """Reference lexicographic policy comparison; does not claim solver optimality."""
    if metrics.hard_violations:
        raise ValueError("A plan violating hard constraints cannot be compared as feasible")
    return tuple(getattr(metrics, name) for name in OBJECTIVES)


def case_policy() -> CasePolicy:
    return CasePolicy.model_validate_json(
        Path(__file__).with_name("case_policy_v1.json").read_text(encoding="utf-8")
    )


def policy_scenarios(path: Path) -> list[dict]:
    """Load reviewable synthetic comparisons, rejecting a different contract version."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if document["policy_id"] != "beeline_case" or document["policy_version"] != 1:
        raise ValueError("Unsupported scenario policy")
    return document["comparisons"]

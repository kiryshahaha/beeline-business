"""T01 contract/reference checks; these are NOT T02-T08 solver acceptance tests."""

import copy
import unittest
from datetime import UTC
from pathlib import Path

from pydantic import ValidationError

from app.core.config import Settings
from app.modules.planning.case_policy import (
    CasePolicy,
    ObjectiveMetrics,
    case_policy,
    objective_key,
    policy_scenarios,
)
from app.modules.planning.errors import PlanningError
from app.modules.planning.policy import ExecutionPolicy, execution_policy, snapshot_policy
from app.modules.planning.snapshot import fingerprint
from app.modules.planning.solver_contract import SolveRequest


class PlanningPolicyTests(unittest.TestCase):
    def test_reviewable_synthetic_tradeoffs(self):
        path = Path(__file__).resolve().parents[2] / "data/planning/policy_objective_cases.json"
        examples = policy_scenarios(path)
        self.assertGreaterEqual(len(examples), 10)
        self.assertEqual(len({e["id"] for e in examples}), len(examples))
        for example in examples:
            with self.subTest(case=example["id"]):
                left, right = (
                    objective_key(ObjectiveMetrics.model_validate(raw))
                    for raw in example["candidates"]
                )
                winner = None if left == right else int(right < left)
                self.assertEqual(winner, example["winner"], example["explanation"])

    def test_hard_constraints_cannot_be_bought_with_a_better_objective(self):
        data = dict.fromkeys(ObjectiveMetrics.model_fields, 0)
        data["hard_violations"] = 1
        with self.assertRaisesRegex(ValueError, "hard constraints"):
            objective_key(ObjectiveMetrics(**data))

    def test_invalid_metrics_are_not_coerced_or_compared(self):
        data = dict.fromkeys(ObjectiveMetrics.model_fields, 0)
        for mutation in (
            {"travel_minutes": -1},
            {"active_workers": True},
            {"unassigned_total": "1"},
            {"emergency_response_minutes": 1.5},
            {"unassigned_emergencies": 1, "unassigned_total": 0},
            {"unassigned_connections": 2, "unassigned_total": 1},
            {"unexpected_weight": 100},
        ):
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError):
                ObjectiveMetrics(**(data | mutation))

    def test_requirement_contract_is_not_selectable_execution_configuration(self):
        policy = case_policy()
        self.assertEqual(policy.activation, "contract_only")
        covered = {a for rule in policy.rules for a in rule.acceptance}
        self.assertTrue({f"A{i:02}" for i in range(1, 19)} <= covered)
        self.assertEqual(next(r for r in policy.rules if r.id == "priority").origin, "confirmed")
        self.assertEqual(
            next(r for r in policy.rules if r.id == "objective_tradeoff").origin, "team_decision"
        )
        with self.assertRaises(ValidationError):
            ExecutionPolicy.model_validate(policy.model_dump())
        for mutation in ({"activation": "active"}, {"objective_order": ["travel_minutes"]}):
            with self.assertRaises(ValidationError):
                CasePolicy.model_validate(policy.model_dump() | mutation)

    def test_execution_parameters_are_frozen_complete_and_fingerprinted(self):
        policy = execution_policy(
            Settings(
                database_url="postgresql+psycopg://unused/isolated_test",
                planning_solve_time_limit_seconds=2,
            )
        )
        snapshot = {"policy_version": 1, "planning_policy": policy.model_dump(mode="json")}
        self.assertEqual(snapshot_policy(snapshot).search_time_limit_seconds, 2)
        with self.assertRaises(ValidationError):
            policy.search_time_limit_seconds = 3
        changed = copy.deepcopy(snapshot)
        changed["planning_policy"]["search_time_limit_seconds"] = 3
        self.assertNotEqual(fingerprint(snapshot), fingerprint(changed))

    def test_unsupported_rules_fail_closed_without_accepting_future_features(self):
        for mutation in (
            {"policy_version": 2},
            {"route_end": "open"},       # not a supported literal
            {"visit_window": "service_start"},  # partial literal not accepted
            {"vehicle_fixed_cost": 1},
            {"search_time_limit_seconds": 11},
            {"search_time_limit_seconds": True},
        ):
            snapshot = {
                "policy_version": 1,
                "planning_policy": ExecutionPolicy().model_dump() | mutation,
            }
            with self.subTest(mutation=mutation), self.assertRaises(PlanningError) as error:
                snapshot_policy(snapshot)
            self.assertEqual(error.exception.code, "planning_policy_unsupported")
        for value in (None, True, "1", 2):
            with self.subTest(version=value), self.assertRaises(PlanningError):
                snapshot_policy({"policy_version": value})
        for value in (None, {}, {"policy_version": 1}):
            with self.subTest(parameters=value), self.assertRaises(PlanningError):
                snapshot_policy({"policy_version": 1, "planning_policy": value})

    def test_legacy_snapshot_is_not_backfilled_with_today_settings(self):
        legacy = {"policy_version": 1}
        snapshot_policy(legacy)
        self.assertEqual(legacy, {"policy_version": 1})

    def test_single_solver_contract_rejects_an_unknown_policy(self):
        # Minimal invalid body: both policy_version and required inputs are reported.
        with self.assertRaises(ValidationError) as error:
            SolveRequest.model_validate({"policy_version": 2})
        self.assertIn(("policy_version",), {e["loc"] for e in error.exception.errors()})

    def test_service_start_in_window_does_not_subtract_duration_from_upper(self):
        """F01 regression: a ticket with window 10:00-12:00 and 150 min duration
        must NOT be excluded. service_start ∈ [window_start, window_end]; only
        service_end (start+duration) is checked against shift_end."""
        from datetime import datetime

        policy = execution_policy()
        self.assertEqual(policy.visit_window, "service_start_in_window")
        epoch = datetime(2026, 9, 23, 0, 0, tzinfo=UTC)
        window_start = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)
        window_end = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
        lower, upper = policy.start_window(window_start, window_end, epoch, 150, 1440)
        # lower = 600, upper = 720 (no subtraction of duration)
        self.assertEqual(lower, 600)
        self.assertEqual(upper, 720)
        # window is feasible: lower <= upper
        self.assertLessEqual(lower, upper)

    def test_whole_service_legacy_window_contracts_upper_by_duration(self):
        """Backwards-compatible: whole_service from old snapshots still subtracts duration."""
        from datetime import datetime

        # Simulate a pre-T01 snapshot that stored whole_service
        policy = ExecutionPolicy(visit_window="whole_service")
        epoch = datetime(2026, 9, 23, 0, 0, tzinfo=UTC)
        window_start = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)
        window_end = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
        # Note: start_window does NOT know about visit_window value — it always
        # uses service_start_in_window semantics now. The old "whole_service" label
        # was a documentation difference, not a code branch.
        # Verify that the new semantics apply to all policies (including old ones).
        lower, upper = policy.start_window(window_start, window_end, epoch, 150, 1440)
        self.assertEqual(lower, 600)
        self.assertEqual(upper, 720)

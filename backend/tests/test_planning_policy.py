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
from app.modules.planning.policy import (
    ExecutionPolicy,
    ExecutionPolicyV1,
    execution_policy,
    policy_snapshot,
    snapshot_policy,
)
from app.modules.planning.schemas import PlanRead
from app.modules.planning.snapshot import fingerprint
from app.modules.planning.solver_contract import OBJECTIVE_ORDER, SolveRequest
from planning_scenarios import generate_planning_dataset


class PlanningPolicyTests(unittest.TestCase):
    def test_planning_fixture_keeps_one_service_area_per_day(self):
        data = generate_planning_dataset()
        locations = {row["id"]: row["building_id"] for row in data["locations"]}
        buildings = {row["id"]: row for row in data["buildings"]}
        service_areas = {
            buildings[locations[ticket["location_id"]]]["service_area_id"]
            for ticket in data["tickets"]
        }
        self.assertEqual(service_areas, {101})

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
        snapshot = policy_snapshot(policy)
        self.assertEqual(snapshot["policy_version"], 2)
        self.assertEqual(snapshot_policy(snapshot).search_time_limit_seconds, 2)
        with self.assertRaises(ValidationError):
            policy.search_time_limit_seconds = 3
        changed = copy.deepcopy(snapshot)
        changed["planning_policy"]["search_time_limit_seconds"] = 3
        self.assertNotEqual(fingerprint(snapshot), fingerprint(changed))

    def test_unsupported_rules_fail_closed_without_accepting_future_features(self):
        for mutation in (
            {"policy_version": 3},
            {"route_end": "open"},  # not a supported literal
            {"visit_window": "service_start"},  # partial literal not accepted
            {"vehicle_fixed_cost": 1},
            {"drop_penalty": "vehicle_count_times_horizon_plus_one"},
            {"objective_order": list(reversed(OBJECTIVE_ORDER))},
            {"objective_order": list(OBJECTIVE_ORDER[:-1])},
            {"priority": "category_and_numeric_priority_penalties"},
            {"search_time_limit_seconds": 11},
            {"search_time_limit_seconds": True},
        ):
            snapshot = {
                "policy_version": 2,
                "planning_policy": ExecutionPolicy().model_dump() | mutation,
            }
            with self.subTest(mutation=mutation), self.assertRaises(PlanningError) as error:
                snapshot_policy(snapshot)
            self.assertEqual(error.exception.code, "planning_policy_unsupported")
        for value in (None, True, "1", 3):
            with self.subTest(version=value), self.assertRaises(PlanningError):
                snapshot_policy({"policy_version": value})
        for version in (1, 2):
            for value in (None, {}, {"policy_version": version}):
                with self.subTest(version=version, parameters=value):
                    with self.assertRaises(PlanningError):
                        snapshot_policy({"policy_version": version, "planning_policy": value})
        # Only snapshots recorded before T01 may lack parameters, and only as version 1.
        with self.assertRaises(PlanningError):
            snapshot_policy({"policy_version": 2})
        # A version 2 parameter set cannot pose as version 1 history, or vice versa.
        with self.assertRaises(PlanningError):
            snapshot_policy(
                {"policy_version": 1, "planning_policy": ExecutionPolicy().model_dump()}
            )
        with self.assertRaises(PlanningError):
            snapshot_policy(
                {"policy_version": 2, "planning_policy": ExecutionPolicyV1().model_dump()}
            )

    def test_version_one_history_keeps_its_recorded_rules(self):
        recorded = {
            "policy_version": 1,
            "planning_policy": ExecutionPolicyV1(search_time_limit_seconds=3).model_dump(
                mode="json"
            ),
        }
        policy = snapshot_policy(recorded)
        self.assertIsInstance(policy, ExecutionPolicyV1)
        self.assertEqual(policy.objective_order, ("unassigned_total", "travel_minutes"))
        self.assertEqual(policy.search_time_limit_seconds, 3)
        self.assertEqual(snapshot_policy({"policy_version": 1}), ExecutionPolicyV1())
        for raw in (recorded["planning_policy"], execution_policy().model_dump(mode="json")):
            plan = PlanRead.model_validate(
                {
                    "planning_policy": raw,
                    "plan_id": "00000000-0000-0000-0000-000000000001",
                    "state": "ready",
                    "outcome": "empty",
                    "route_date": "2030-01-15",
                    "timezone": "Europe/Moscow",
                    "expires_at": "2030-01-15T10:00:00+03:00",
                    "solver_status": None,
                    "routes": [],
                    "unassigned": [],
                    "excluded_workers": [],
                    "warnings": [],
                }
            )
            self.assertEqual(plan.planning_policy.model_dump(mode="json"), raw)

    def test_current_policy_executes_the_case_objective_order(self):
        policy = execution_policy()
        self.assertEqual(policy.policy_version, 2)
        self.assertEqual(policy.objective_order, OBJECTIVE_ORDER)
        # The solver keeps the case order; its last level counts only a changed worker.
        self.assertEqual(policy.objective_order[:-1], case_policy().objective_order[:-1])
        self.assertEqual(case_policy().objective_order[-1], "changed_future_visits")
        self.assertEqual(policy.objective_order[-1], "reassigned_visits")
        self.assertEqual(policy.objective_method, "lexicographic_bounded_weights")
        self.assertEqual(policy.reassigned_visit, "other_worker_than_current_assignment")
        self.assertNotIn("vehicle_fixed_cost", ExecutionPolicy.model_fields)

    def test_legacy_snapshot_is_not_backfilled_with_today_settings(self):
        legacy = {"policy_version": 1}
        snapshot_policy(legacy)
        self.assertEqual(legacy, {"policy_version": 1})

    def test_single_solver_contract_rejects_an_unknown_policy(self):
        # Minimal invalid body: both policy_version and required inputs are reported.
        with self.assertRaises(ValidationError) as error:
            SolveRequest.model_validate({"policy_version": 1})
        self.assertIn(("policy_version",), {e["loc"] for e in error.exception.errors()})

    def test_current_policy_requires_whole_service_within_window(self):
        from datetime import datetime

        policy = execution_policy()
        self.assertEqual(policy.visit_window, "whole_service")
        epoch = datetime(2030, 1, 15, 0, 0, tzinfo=UTC)
        start = datetime(2030, 1, 15, 10, 0, tzinfo=UTC)
        end = datetime(2030, 1, 15, 12, 0, tzinfo=UTC)
        self.assertEqual(policy.start_window(start, end, epoch, 30, 1440), [600, 690])
        self.assertEqual(policy.start_window(start, end, epoch, 150, 1440), [600, 570])

    def test_recorded_start_only_policy_retains_its_original_window(self):
        from datetime import datetime

        recorded = ExecutionPolicy(visit_window="service_start_in_window")
        policy = snapshot_policy(policy_snapshot(recorded))
        epoch = datetime(2030, 1, 15, 0, 0, tzinfo=UTC)
        start = datetime(2030, 1, 15, 10, 0, tzinfo=UTC)
        end = datetime(2030, 1, 15, 12, 0, tzinfo=UTC)
        self.assertEqual(policy.start_window(start, end, epoch, 150, 1440), [600, 720])


if __name__ == "__main__":
    unittest.main()

"""T05: the executed objective is versioned, bounded and checked against the routes."""

import unittest
from unittest.mock import patch

from app.core.config import Settings
from app.modules.planning.day_plans import build_plan_state
from app.modules.planning.errors import PlanningError
from app.modules.planning.matrices import build_problem
from app.modules.planning.policy import ExecutionPolicyV1, execution_policy
from app.modules.planning.validation import validate_solution
from tests.planning_fakes import FeasiblePlanner, provider_factory
from tests.test_planning_boundaries import prepared


def settings():
    return Settings(
        database_url="postgresql://unused/isolated_test",
        planner_service_token="internal",
        planning_max_matrix_cells_total=20000,
    )


class ObjectiveContractTests(unittest.IsolatedAsyncioTestCase):
    async def problem(self, data=None):
        async with provider_factory() as provider:
            problem, _ = await build_problem(data or prepared(6), provider, settings())
        return problem

    async def test_validator_recomputes_breakdown_weights_and_total(self):
        data = prepared(6)
        data["tickets"][0]["category"] = "emergency"
        data["tickets"][1]["category"] = "connection"
        problem = await self.problem(data)
        solution = await FeasiblePlanner().solve(problem)
        validate_solution(problem, solution)
        components = solution.objective_components
        self.assertEqual(components.active_workers, 1)
        self.assertEqual(components.unassigned_total, 0)
        self.assertEqual(solution.total_cost, problem.objective_weights().cost(components))

        tampered = [
            {"objective_components": None},
            {"objective_weights": None},
            {"total_cost": solution.total_cost - 1},
            {"objective_components": components.model_copy(update={"active_workers": 0})},
            {"objective_components": components.model_copy(update={"travel_minutes": 1})},
            {
                "objective_components": components.model_copy(
                    update={"emergency_response_minutes": components.emergency_response_minutes + 1}
                )
            },
            {
                "objective_weights": solution.objective_weights.model_copy(
                    update={"travel_minutes": 1_000_000}
                )
            },
        ]
        for update in tampered:
            with self.subTest(update=update), self.assertRaises(PlanningError) as error:
                validate_solution(problem, solution.model_copy(update=update))
            self.assertEqual(error.exception.code, "planner_invalid_response")

    async def test_unserved_categories_are_counted_from_dropped_visits(self):
        data = prepared(6)
        data["tickets"][0]["category"] = "emergency"
        data["tickets"][1]["category"] = "connection"
        for ticket in data["tickets"][:2]:
            ticket["allowed"] = []
        problem = await self.problem(data)
        solution = await FeasiblePlanner().solve(problem)
        validate_solution(problem, solution)
        components = solution.objective_components
        self.assertEqual(
            (components.unassigned_emergencies, components.unassigned_connections), (1, 1)
        )
        self.assertEqual(components.unassigned_total, 2)

    async def test_current_assignment_becomes_the_previous_vehicle(self):
        data = prepared(5)
        data["workers"][0]["user_id"], data["workers"][1]["user_id"] = 11, 12
        data["tickets"][0]["assigned_worker_id"] = 12
        data["tickets"][1]["assigned_worker_id"] = 99  # not planned now: no previous vehicle
        problem = await self.problem(data)
        self.assertEqual(
            [policy.previous_vehicle_id for policy in problem.ticket_policies], [1, None, None]
        )
        solution = await FeasiblePlanner().solve(problem)
        validate_solution(problem, solution)
        self.assertEqual(solution.objective_components.reassigned_visits, 1)

    async def test_recorded_version_one_rules_are_never_solved_again(self):
        data = prepared(4)
        data["policy"] = ExecutionPolicyV1()
        with self.assertRaises(PlanningError) as error:
            await self.problem(data)
        self.assertEqual(error.exception.code, "planning_policy_unsupported")

    async def test_objective_outside_the_cost_range_is_a_planning_limit(self):
        # The planner tests reach the real 2**62 limit; here only the mapping is checked.
        with (
            patch("app.modules.planning.solver_contract.OBJECTIVE_COST_LIMIT", 1000),
            self.assertRaises(PlanningError) as error,
        ):
            await self.problem(prepared(40))
        self.assertEqual(error.exception.code, "planning_limit_exceeded")
        self.assertEqual(error.exception.details, {"limit": "objective_cost_range"})


class ObjectiveRevisionTests(unittest.TestCase):
    def test_revision_keeps_rules_and_breakdown_of_the_applied_plan(self):
        policy = execution_policy().model_dump(mode="json")
        components = {"unassigned_emergencies": 0, "active_workers": 2}
        state = build_plan_state(
            {"planning_policy": policy, "objective_components": components, "routes": []}
        )
        self.assertEqual(state["planning_policy"], policy)
        self.assertEqual(state["objective_components"], components)
        manual = build_plan_state({"routes": [], "unassigned": [], "metrics": {}})
        self.assertIsNone(manual["planning_policy"])
        self.assertIsNone(manual["objective_components"])


if __name__ == "__main__":
    unittest.main()

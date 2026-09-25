"""Committed PostgreSQL tests of preview, atomic application and invalidation."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import create_access_token
from app.db.models import (
    Location,
    PlanningPlan,
    PlanningPlanRoute,
    Route,
    Ticket,
    TicketAppliance,
    WorkerSkillAssignment,
    WorkTypePlanningRule,
    WorkTypeRequiredAppliance,
)
from app.db.session import get_session
from app.main import app
from app.modules.data_exchange.formats import parse_file, serialize
from app.modules.data_exchange.service import import_data
from app.modules.planning import router as api
from app.modules.planning import service
from app.modules.planning.errors import PlanningError
from app.modules.planning.snapshot import fingerprint
from app.modules.planning.solver_contract import SolveResponse
from planning_scenarios import NOW, generate_planning_dataset, preview_request
from tests.planning_fakes import FeasiblePlanner, provider_factory
from tests.support import CommittedDatabaseTestCase


class PlanningApiTests(CommittedDatabaseTestCase):
    def setUp(self):
        super().setUp()
        # Only password hashing is avoided in these token-authenticated fixtures.
        # User authentication itself uses the real dependency and database.
        self.data = generate_planning_dataset()
        with (
            Session(self.engine) as session,
            patch(
                "app.modules.data_exchange.service.hash_password",
                return_value="fixture-unused-hash",
            ),
        ):
            self.receipt = import_data(session, parse_file(serialize(self.data, "csv"), "data.zip"))
        self.payload = preview_request(self.receipt, self.data)
        self.now = NOW
        self.settings = Settings(planning_enabled=True)

        def session_dependency():
            with Session(self.engine) as session:
                yield session

        overrides = {
            get_session: session_dependency,
            api.get_planning_engine: lambda: self.engine,
            api.planning_settings: lambda: self.settings,
            api.get_provider_factory: lambda: provider_factory,
            api.get_planner_client: FeasiblePlanner,
            api.get_clock: lambda: lambda: self.now,
        }
        app.dependency_overrides.update(overrides)
        self.addCleanup(lambda: [app.dependency_overrides.pop(k, None) for k in overrides])
        self.client = self.enterContext(TestClient(app))
        self.headers = self.auth(1)

    def auth(self, source_id):
        return {
            "Authorization": "Bearer "
            + create_access_token({"sub": str(self.receipt["id_map"]["users"][str(source_id)])})
        }

    def preview(self, **overrides):
        response = self.client.post(
            "/api/v1/planning/preview", json={**self.payload, **overrides}, headers=self.headers
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def apply(self, plan):
        return self.client.post(
            f"/api/v1/planning/plans/{plan['plan_id']}/apply", headers=self.headers
        )

    def counts(self):
        with Session(self.engine) as session:
            return (
                session.scalar(select(func.count(Route.id))),
                session.scalar(
                    select(func.count(Ticket.id)).where(Ticket.assigned_worker_id.is_not(None))
                ),
                session.scalar(select(func.count()).select_from(PlanningPlanRoute)),
            )

    def test_preview_is_read_only_for_domain_and_apply_is_atomic_idempotent(self):
        self.assertEqual(self.counts(), (0, 0, 0))
        plan = self.preview(allow_partial=False)
        self.assertEqual(plan["unassigned"], [])
        self.assertEqual(len(plan["routes"]), 4)
        self.assertEqual(self.counts(), (0, 0, 0))
        response = self.apply(plan)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.counts(), (4, 24, 4))
        self.assertTrue(all(r["route_number"] == 1 for r in response.json()["routes"]))
        retry = self.apply(plan)
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertTrue(retry.json()["already_applied"])
        self.assertEqual(self.counts(), (4, 24, 4))
        read = self.client.get(f"/api/v1/planning/plans/{plan['plan_id']}", headers=self.headers)
        self.assertTrue(read.json()["is_current"], read.text)
        with Session(self.engine) as session:
            for ticket in session.scalars(select(Ticket)):
                self.assertIsNotNone(ticket.planned_start_at)
                self.assertEqual(
                    ticket.planned_end_at - ticket.planned_start_at, timedelta(minutes=20)
                )
            for route in session.scalars(select(Route)):
                self.assertEqual(route.geojson["features"][-1]["properties"]["source"], "geoapify")

    def test_policy_is_saved_with_actual_search_parameters_and_survives_settings_change(self):
        self.settings.planning_solve_time_limit_seconds = 2
        plan = self.preview()
        recorded = plan["planning_policy"]
        self.assertEqual(recorded["search_time_limit_seconds"], 2)
        with Session(self.engine) as session:
            stored = session.get(PlanningPlan, UUID(plan["plan_id"]))
            self.assertEqual(stored.input_snapshot["planning_policy"], recorded)
            self.assertEqual(stored.result_snapshot["problem"]["search_time_limit_s"], 2)
            self.assertEqual(stored.result_snapshot["problem"]["policy_version"], 1)
        self.settings.planning_solve_time_limit_seconds = 7
        self.assertEqual(self.apply(plan).status_code, 200)
        read = self.client.get(f"/api/v1/planning/plans/{plan['plan_id']}", headers=self.headers)
        self.assertEqual(read.json()["planning_policy"], recorded)
        self.assertTrue(read.json()["is_current"])
        self.assertTrue(self.apply(plan).json()["already_applied"])

    def test_legacy_preview_applies_without_inventing_missing_historical_parameters(self):
        plan = self.preview()
        with Session(self.engine) as session, session.begin():
            stored = session.get(PlanningPlan, UUID(plan["plan_id"]))
            legacy = {k: v for k, v in stored.input_snapshot.items() if k != "planning_policy"}
            stored.input_snapshot = legacy
            stored.input_fingerprint = fingerprint(legacy)
            result = dict(stored.result_snapshot)
            result["public"] = {k: v for k, v in result["public"].items() if k != "planning_policy"}
            result["problem"] = {
                k: v for k, v in result["problem"].items() if k != "policy_version"
            }
            stored.result_snapshot = result
        self.assertEqual(self.apply(plan).status_code, 200)
        read = self.client.get(f"/api/v1/planning/plans/{plan['plan_id']}", headers=self.headers)
        self.assertIsNone(read.json()["planning_policy"])
        self.assertTrue(read.json()["is_current"])
        with Session(self.engine) as session:
            stored = session.get(PlanningPlan, UUID(plan["plan_id"]))
            self.assertNotIn("planning_policy", stored.input_snapshot)

    def test_unknown_policy_cannot_apply_or_write_routes(self):
        plan = self.preview()
        with Session(self.engine) as session, session.begin():
            stored = session.get(PlanningPlan, UUID(plan["plan_id"]))
            stored.input_snapshot = stored.input_snapshot | {"policy_version": 999}
        response = self.apply(plan)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "planning_policy_unsupported")
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_incomplete_policy_cannot_acquire_defaults_during_apply(self):
        plan = self.preview()
        with Session(self.engine) as session, session.begin():
            stored = session.get(PlanningPlan, UUID(plan["plan_id"]))
            stored.input_snapshot = stored.input_snapshot | {
                "planning_policy": {"policy_version": 1}
            }
        response = self.apply(plan)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "planning_policy_unsupported")
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_policy_read_requires_observer_and_distinguishes_contract_from_execution(self):
        url = "/api/v1/planning/policy"
        for headers, status in (({}, 401), (self.auth(9), 403), (self.auth(3), 403)):
            self.assertEqual(self.client.get(url, headers=headers).status_code, status)
        response = self.client.get(url, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["case_contract"]["activation"], "contract_only")
        self.assertEqual(
            response.json()["execution"]["priority"],
            "category_and_numeric_priority_penalties",
        )

    def test_preview_cannot_silently_activate_case_policy(self):
        response = self.client.post(
            "/api/v1/planning/preview",
            headers=self.headers,
            json=self.payload | {"planning_policy": {"route_end": "open"}},
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_concurrent_apply_creates_exactly_one_receipt(self):
        plan = self.preview()

        def apply_once(_):
            return service.apply_plan(self.engine, UUID(plan["plan_id"]), lambda: self.now)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(apply_once, range(2)))
        self.assertEqual(sorted(r["already_applied"] for r in results), [False, True])
        self.assertEqual(self.counts(), (4, 24, 4))

    def test_overlapping_previews_cannot_double_assign(self):
        first, second = self.preview(), self.preview()
        self.assertEqual(self.apply(first).status_code, 200)
        response = self.apply(second)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "plan_stale")
        self.assertEqual(self.counts(), (4, 24, 4))

    def test_stale_ticket_change_refuses_every_write(self):
        plan = self.preview()
        with self.engine.begin() as connection:
            connection.execute(
                update(Ticket)
                .where(Ticket.id == self.payload["ticket_ids"][0])
                .values(estimated_duration_minutes=120)
            )
        response = self.apply(plan)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_expired_preview_and_successful_retry_after_expiration(self):
        first = self.preview()
        self.now += timedelta(seconds=301)
        self.assertEqual(self.apply(first).json()["detail"]["code"], "plan_expired")
        second = self.preview()
        self.assertEqual(self.apply(second).status_code, 200)
        self.now += timedelta(days=10)
        self.assertTrue(self.apply(second).json()["already_applied"])

    def test_failure_during_assignments_rolls_back_routes_and_notifications(self):
        plan = self.preview()
        with patch.object(
            service, "update_assignment_in_transaction", side_effect=RuntimeError("failure")
        ):
            with self.assertRaises(RuntimeError):
                service.apply_plan(self.engine, UUID(plan["plan_id"]), lambda: self.now)
        self.assertEqual(self.counts(), (0, 0, 0))
        self.assertEqual(self.apply(plan).status_code, 200)

    def test_roles_and_invalid_input_are_rejected_before_provider_calls(self):
        for headers, status in (({}, 401), (self.auth(9), 403), (self.auth(3), 403)):
            response = self.client.post(
                "/api/v1/planning/preview", json=self.payload, headers=headers
            )
            self.assertEqual(response.status_code, status, response.text)
        for update_values in (
            {"worker_id": None},
            {"ticket_ids": [True]},
            {"ticket_ids": [1, 1]},
            {"time_matrix": []},
        ):
            response = self.client.post(
                "/api/v1/planning/preview",
                json={**self.payload, **update_values},
                headers=self.headers,
            )
            self.assertEqual(response.status_code, 422, response.text)

    def test_missing_ids_and_configuration_are_explained(self):
        response = self.client.post(
            "/api/v1/planning/preview",
            json={**self.payload, "ticket_ids": [2147483647]},
            headers=self.headers,
        )
        self.assertEqual(response.json()["detail"]["code"], "unknown_ids")
        with self.engine.begin() as connection:
            connection.execute(WorkTypePlanningRule.__table__.delete())
        plan = self.preview()
        self.assertEqual((plan["outcome"], plan["solver_status"]), ("empty", None))
        self.assertEqual(plan["routes"], [])
        self.assertEqual(
            plan["metrics"],
            {
                "requested_tickets": 24,
                "eligible_tickets": 0,
                "assigned_tickets": 0,
                "unassigned_tickets": 24,
                "requested_workers": 4,
                "available_workers": 4,
                "used_workers": 0,
                "distance_meters": 0.0,
                "travel_minutes": 0,
                "service_minutes": 0,
                "waiting_minutes": 0,
                "unassigned_by_category": {"data": 24},
            },
        )
        reasons = [x["reason"] for x in plan["unassigned"]]
        self.assertEqual({r["code"] for r in reasons}, {"work_requirements_not_configured"})
        self.assertTrue(all("не настроены требования" in r["message"] for r in reasons))
        self.assertTrue(all(len(r["ids"]["work_type_ids"]) == 1 for r in reasons))
        read = self.client.get(f"/api/v1/planning/plans/{plan['plan_id']}", headers=self.headers)
        self.assertEqual(read.json()["unassigned"], plan["unassigned"])
        response = self.apply(plan)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "plan_has_no_assignments")
        self.assertEqual(self.counts(), (0, 0, 0))
        strict = self.client.post(
            "/api/v1/planning/preview",
            json={**self.payload, "allow_partial": False},
            headers=self.headers,
        )
        self.assertEqual(strict.status_code, 422, strict.text)
        self.assertEqual(strict.json()["detail"]["code"], "incomplete_plan")
        self.assertEqual(strict.json()["detail"]["unassigned"], plan["unassigned"])

    def test_planned_visit_lists_checked_factors(self):
        plan = self.preview(allow_partial=False)
        self.assertEqual(plan["outcome"], "complete")
        self.assertEqual(plan["metrics"]["assigned_tickets"], 24)
        self.assertEqual(plan["metrics"]["used_workers"], 4)
        self.assertIsNone(plan["resource_estimate"])
        for route in plan["routes"]:
            for visit in route["stops"]:
                factors = {f["code"]: f for f in visit["factors"]}
                self.assertEqual(
                    list(factors),
                    [
                        "skills_match",
                        "transport",
                        "start_in_window",
                        "equipment_reserved",
                        "priority_applied",
                        "no_sla_deadline",
                        "only_eligible_worker",
                    ],
                )
                self.assertEqual(
                    factors["start_in_window"]["observed"]["service_start_at"],
                    visit["service_start_at"],
                )
                self.assertEqual(
                    factors["transport"]["observed"]["transport_type"], route["transport_type"]
                )

    def test_several_candidates_are_not_presented_as_a_unique_best_engineer(self):
        with self.engine.begin() as connection:
            connection.execute(TicketAppliance.__table__.delete())
            connection.execute(WorkTypeRequiredAppliance.__table__.delete())
        plan = self.preview(allow_partial=False)
        for route in plan["routes"]:
            for visit in route["stops"]:
                selection = visit["factors"][-1]
                self.assertEqual(selection["code"], "selected_by_plan_objective")
                self.assertEqual(selection["observed"], {"eligible_workers": 4})
                self.assertIn("без отдельного сравнения", selection["message"])
                self.assertEqual(visit["factors"][3]["code"], "no_equipment_required")

    def test_missing_skill_names_the_skill_nobody_has(self):
        skill_id = self.receipt["id_map"]["worker_skills"]["1"]
        with self.engine.begin() as connection:
            connection.execute(
                WorkerSkillAssignment.__table__.delete().where(
                    WorkerSkillAssignment.skill_id == skill_id
                )
            )
        plan = self.preview()
        self.assertEqual(plan["outcome"], "partial")
        rejected = [x for x in plan["unassigned"] if x["reason"]["code"] == "missing_skill"]
        self.assertEqual(len(rejected), 8)
        self.assertEqual(len(plan["unassigned"]), 8)
        for item in rejected:
            self.assertEqual(item["reason"]["category"], "skill")
            self.assertEqual(item["reason"]["ids"], {"skill_ids": [skill_id]})
            self.assertIn(f"№{skill_id}", item["reason"]["message"])
            self.assertEqual(
                {c["worker_id"] for c in item["candidates"]}, set(self.payload["worker_ids"])
            )
            self.assertEqual({c["reason"]["code"] for c in item["candidates"]}, {"missing_skill"})
        self.assertEqual(plan["metrics"]["unassigned_by_category"], {"skill": 8})

    def test_full_routes_are_not_called_impossible_and_extra_staff_is_an_estimate(self):
        with self.engine.begin() as connection:
            connection.execute(update(Ticket).values(estimated_duration_minutes=240))
        plan = self.preview()
        self.assertEqual(plan["outcome"], "partial")
        self.assertEqual(plan["metrics"]["assigned_tickets"], 8)
        self.assertEqual(len(plan["unassigned"]), 16)
        for item in plan["unassigned"]:
            self.assertEqual(item["reason"]["code"], "no_slot_in_computed_plan")
            self.assertIn("не доказательство невозможности", item["reason"]["message"])
            codes = sorted(c["reason"]["code"] for c in item["candidates"])
            self.assertEqual(codes, ["office_mismatch"] * 3 + ["route_full"])
        estimate = plan["resource_estimate"]
        self.assertTrue(estimate["is_estimate"])
        self.assertTrue(estimate["complete"])
        self.assertEqual(estimate["additional_workers"], 8)
        self.assertEqual(estimate["uncovered_ticket_ids"], [])
        self.assertEqual(
            estimate["covered_ticket_ids"], sorted(x["ticket_id"] for x in plan["unassigned"])
        )
        self.assertEqual(
            {w["like_worker_id"] for w in estimate["workers"]}, set(self.payload["worker_ids"])
        )
        self.assertIn("не доказанный минимальный штат", estimate["message"])

    def test_missed_slot_is_reported_as_search_limit_not_impossibility(self):
        class LazyPlanner(FeasiblePlanner):
            async def solve(self, problem):
                restricted = problem.model_copy(deep=True)
                restricted.allowed_vehicles[max(restricted.allowed_vehicles, key=int)] = []
                return await super().solve(restricted)

        app.dependency_overrides[api.get_planner_client] = LazyPlanner
        plan = self.preview()
        self.assertEqual(len(plan["unassigned"]), 1)
        item = plan["unassigned"][0]
        self.assertEqual(item["reason"]["code"], "feasible_slot_missed")
        self.assertEqual(item["reason"]["category"], "search")
        self.assertEqual(
            item["reason"]["observed"],
            {"search_time_limit_seconds": 5, "category": "repair", "priority": 3},
        )
        slots = [c for c in item["candidates"] if c["reason"]["code"] == "slot_available"]
        self.assertEqual(len(slots), 1)
        self.assertEqual(item["reason"]["ids"], {"worker_ids": [slots[0]["worker_id"]]})
        self.assertIsNone(plan["resource_estimate"])

    def test_solver_without_solution_is_an_infrastructure_error_not_an_empty_plan(self):
        class SilentPlanner:
            async def solve(self, _):
                return SolveResponse(status="NOT_SOLVED", solver_status_code=0)

        app.dependency_overrides[api.get_planner_client] = SilentPlanner
        response = self.client.post(
            "/api/v1/planning/preview", json=self.payload, headers=self.headers
        )
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(
            response.json()["detail"], {"code": "planner_not_solved", "retryable": True}
        )
        with Session(self.engine) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(PlanningPlan)), 0)

    def test_plan_saved_before_structured_reasons_is_still_readable(self):
        with self.engine.begin() as connection:
            connection.execute(
                update(Ticket)
                .where(Ticket.id == self.payload["ticket_ids"][0])
                .values(work_type="unknown", work_type_id=None)
            )
        plan = self.preview()
        with Session(self.engine) as session, session.begin():
            stored = session.get(PlanningPlan, UUID(plan["plan_id"]))
            result = dict(stored.result_snapshot)
            public = {
                k: v
                for k, v in result["public"].items()
                if k not in ("outcome", "metrics", "resource_estimate")
            }
            public["unassigned"] = [
                {"ticket_id": x["ticket_id"], "reason": x["reason"]["code"]}
                for x in public["unassigned"]
            ]
            for route in public["routes"]:
                for visit in route["stops"]:
                    del visit["factors"]
            result["public"] = public
            stored.result_snapshot = result
        read = self.client.get(f"/api/v1/planning/plans/{plan['plan_id']}", headers=self.headers)
        self.assertEqual(read.status_code, 200, read.text)
        body = read.json()
        self.assertEqual(body["outcome"], "partial")
        self.assertNotIn("metrics", body)
        self.assertEqual(body["unassigned"][0]["reason"]["code"], "unknown_work_type")
        self.assertEqual(body["unassigned"][0]["reason"]["category"], "data")
        self.assertEqual(body["unassigned"][0]["candidates"], [])
        self.assertEqual(self.apply(plan).status_code, 200)

    def test_rules_api_requires_explicit_eligibility_and_controls_norm_duration(self):
        work_type_id = self.receipt["id_map"]["work_types"]["1"]
        url = f"/api/v1/work-types/{work_type_id}/planning-rules"
        rules = {
            "service_duration_source": "work_norm",
            "required_skill_ids": [],
            "required_appliances": [],
        }
        self.assertEqual(self.client.put(url, json=rules, headers=self.auth(9)).status_code, 403)
        response = self.client.put(url, json=rules, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        plan = self.preview()
        changed = set(self.payload["ticket_ids"][::3])
        for route in plan["routes"]:
            for visit in route["stops"]:
                if visit["ticket_id"] in changed:
                    # travel_minutes=15 is excluded: matrix already accounts for travel.
                    self.assertEqual(visit["effective_service_minutes"], 40)

    def test_partial_preview_lists_every_unassigned_ticket(self):
        with self.engine.begin() as connection:
            connection.execute(
                update(Ticket)
                .where(Ticket.id == self.payload["ticket_ids"][0])
                .values(work_type="unknown", work_type_id=None)
            )
        plan = self.preview()
        self.assertEqual(
            plan["unassigned"],
            [
                {
                    "ticket_id": self.payload["ticket_ids"][0],
                    "reason": {
                        "code": "unknown_work_type",
                        "category": "data",
                        "message": "Вид работ «unknown» не найден в справочнике",
                        "constraint": None,
                        "ids": {},
                        "observed": {
                            "work_type": "unknown",
                            "category": "repair",
                            "priority": 3,
                        },
                        "required": {
                            "planning_priority_order": [
                                "emergency",
                                "connection",
                                "repair",
                                "additional",
                            ],
                            "ticket_priority": 3,
                        },
                    },
                    "candidates": [],
                }
            ],
        )
        self.assertEqual(plan["outcome"], "partial")
        self.assertEqual(plan["metrics"]["unassigned_by_category"], {"data": 1})
        response = self.client.post(
            "/api/v1/planning/preview",
            json={**self.payload, "allow_partial": False},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_malicious_planner_output_never_becomes_a_preview(self):
        class InvalidPlanner(FeasiblePlanner):
            async def solve(self, problem):
                answer = await super().solve(problem)
                answer.routes[0].steps[1].arrival_time = 0
                return answer

        app.dependency_overrides[api.get_planner_client] = InvalidPlanner
        response = self.client.post(
            "/api/v1/planning/preview", json=self.payload, headers=self.headers
        )
        self.assertEqual(response.status_code, 502, response.text)
        with Session(self.engine) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(PlanningPlan)), 0)

    def test_planner_outage_is_reported_without_domain_writes(self):
        class FailedPlanner:
            async def solve(self, _):
                raise PlanningError("planner_timeout", 504)

        app.dependency_overrides[api.get_planner_client] = FailedPlanner
        response = self.client.post(
            "/api/v1/planning/preview", json=self.payload, headers=self.headers
        )
        self.assertEqual(response.status_code, 504, response.text)
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_configuring_observer_cannot_be_deleted_through_a_foreign_key_error(self):
        observer_id = self.receipt["id_map"]["users"]["1"]
        response = self.client.delete(f"/api/v1/users/{observer_id}", headers=self.auth(2))
        self.assertEqual(response.status_code, 409, response.text)

    def test_apply_rejects_client_replacement_of_saved_routes(self):
        plan = self.preview()
        response = self.client.post(
            f"/api/v1/planning/plans/{plan['plan_id']}/apply",
            json={"routes": []},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_coincident_stops_expose_null_geometry_and_preserve_each_visit(self):
        with self.engine.begin() as connection:
            connection.execute(update(Location).values(latitude=55.75, longitude=37.61))
        plan = self.preview(allow_partial=False)
        self.assertEqual(sum(len(r["stops"]) for r in plan["routes"]), 24)
        for route in plan["routes"]:
            self.assertIn("geometry", route)
            self.assertIsNone(route["geometry"])
            self.assertEqual(route["travel_minutes"], 0)
        self.assertEqual(self.apply(plan).status_code, 200)

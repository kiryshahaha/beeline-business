"""T09: one current day plan per service area, an immutable history and an exact diff.

Covers A19 (two revisions, unchanged historical geometry, precise diff, consumers see
the current one) and the A20 part about a proposal that the area-day has moved past.
"""

import copy
import unittest
from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import create_access_token
from app.db.models import DayPlanRevision, Route, ServiceArea, Ticket
from app.db.session import get_session
from app.main import app
from app.modules.data_exchange.formats import parse_file, serialize
from app.modules.data_exchange.service import import_data
from app.modules.planning import day_plans
from app.modules.planning import router as api
from planning_scenarios import NOW, ROUTE_DATE, generate_planning_dataset, preview_request
from tests.planning_fakes import FeasiblePlanner, provider_factory
from tests.support import CommittedDatabaseTestCase


class DiffSemanticsTests(unittest.TestCase):
    """The diff is read by a dispatcher, so it names what actually moved."""

    def state(self, visits, **metrics):
        return {
            "visits": visits,
            "unassigned_ticket_ids": [],
            "metrics": {"distance_meters": 1000.0, "assigned_tickets": len(visits), **metrics},
        }

    def visit(self, ticket_id, worker_id, sequence, start):
        return {
            "ticket_id": ticket_id,
            "worker_id": worker_id,
            "route_id": None,
            "sequence": sequence,
            "arrival_at": f"2030-01-15T{start:02d}:00:00+00:00",
            "service_start_at": f"2030-01-15T{start:02d}:05:00+00:00",
            "service_end_at": f"2030-01-15T{start:02d}:35:00+00:00",
        }

    def test_diff_reports_assignee_order_times_added_removed_and_metrics(self):
        before = self.state(
            [self.visit(1, 7, 1, 9), self.visit(2, 7, 2, 11), self.visit(3, 8, 1, 10)]
        )
        after = self.state(
            [self.visit(1, 8, 2, 12), self.visit(2, 7, 1, 11), self.visit(4, 8, 1, 9)],
            distance_meters=1500.0,
        )
        diff = day_plans.diff_states(before, after)

        self.assertEqual([item["ticket_id"] for item in diff["added"]], [4])
        self.assertEqual([item["ticket_id"] for item in diff["removed"]], [3])
        changes = {item["ticket_id"]: item["changes"] for item in diff["changed"]}
        self.assertEqual(changes[1]["worker_id"], {"from": 7, "to": 8})
        self.assertEqual(changes[1]["sequence"], {"from": 1, "to": 2})
        self.assertEqual(
            changes[1]["service_start_at"],
            {"from": "2030-01-15T09:05:00+00:00", "to": "2030-01-15T12:05:00+00:00"},
        )
        # Ticket 2 only moved up the route; its promised times did not change.
        self.assertEqual(set(changes[2]), {"sequence"})
        self.assertEqual(diff["unchanged_ticket_ids"], [])
        self.assertEqual(
            diff["metrics"]["distance_meters"], {"from": 1000.0, "to": 1500.0, "delta": 500.0}
        )

    def test_untouched_visits_are_listed_separately_from_changes(self):
        state = self.state([self.visit(1, 7, 1, 9), self.visit(2, 7, 2, 11)])
        diff = day_plans.diff_states(state, state)
        self.assertEqual(diff["changed"], [])
        self.assertEqual(diff["unchanged_ticket_ids"], [1, 2])
        self.assertEqual(diff["metrics"], {})

    def test_first_revision_of_a_day_adds_every_visit(self):
        after = self.state([self.visit(1, 7, 1, 9)])
        diff = day_plans.diff_states(None, after)
        self.assertEqual([item["ticket_id"] for item in diff["added"]], [1])
        self.assertEqual(diff["removed"], [])


class DayPlanRevisionApiTests(CommittedDatabaseTestCase):
    def setUp(self):
        super().setUp()
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
        self.area_id = self.receipt["id_map"]["service_areas"]["101"]

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

    def day_url(self, suffix=""):
        return f"/api/v1/planning/areas/{self.area_id}/{ROUTE_DATE.isoformat()}{suffix}"

    def preview(self, **overrides):
        response = self.client.post(
            "/api/v1/planning/preview", json={**self.payload, **overrides}, headers=self.headers
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def apply(self, plan):
        response = self.client.post(
            f"/api/v1/planning/plans/{plan['plan_id']}/apply", headers=self.headers
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def publish_manual_edit(self, mutate):
        """Publish the next revision the way a manual correction would."""
        with Session(self.engine) as session, session.begin():
            current = session.scalar(
                select(DayPlanRevision).where(
                    DayPlanRevision.service_area_id == self.area_id,
                    DayPlanRevision.route_date == ROUTE_DATE,
                    DayPlanRevision.is_current.is_(True),
                )
            )
            state = {**current.plan_state, "visits": mutate(list(current.plan_state["visits"]))}
            return day_plans.publish_revision(
                session,
                service_area_id=self.area_id,
                route_date=ROUTE_DATE,
                actor_id=self.receipt["id_map"]["users"]["1"],
                reason="manual_edit",
                fingerprint="b" * 64,
                plan_state=state,
                result={},
                at=self.now + timedelta(hours=1),
            ).revision

    def test_legacy_revision_import_resolves_its_service_area(self):
        source = copy.deepcopy(self.data["day_plan_revisions"][0])
        source["id"] = 900_000
        source.pop("plan_id", None)
        source.pop("service_area_id")
        source["_legacy_district_id"] = 1
        source["actor_id"] = self.receipt["id_map"]["users"][str(source["actor_id"])]
        source["event_id"] = None

        legacy_district = copy.deepcopy(self.data["districts"][0])
        legacy_district["city_id"] = self.receipt["id_map"]["cities"][
            str(legacy_district["city_id"])
        ]
        legacy_district["name"] = "Район из старого архива"
        legacy_package = {"districts": [legacy_district]}
        legacy_package["day_plan_revisions"] = [source]
        with Session(self.engine) as session:
            receipt = import_data(session, legacy_package)

        imported_id = receipt["id_map"]["day_plan_revisions"]["900000"]
        with Session(self.engine) as session:
            imported = session.get(DayPlanRevision, imported_id)
            district_row_id = receipt["id_map"]["districts"]["1"]
            expected_area_id = session.scalar(
                select(ServiceArea.id).where(ServiceArea.code == f"district_{district_row_id}")
            )
        self.assertEqual(imported.service_area_id, expected_area_id)

    def test_apply_publishes_one_current_revision_and_never_rewrites_history(self):
        applied = self.apply(self.preview(allow_partial=False))
        first = applied["day_revision"]

        with Session(self.engine) as session:
            historical_geometry = {
                route.id: route.geojson for route in session.scalars(select(Route))
            }
        current = self.client.get(self.day_url("/current"), headers=self.headers)
        self.assertEqual(current.status_code, 200, current.text)
        self.assertEqual(current.json()["revision"], first)
        self.assertEqual(current.json()["reason"], "plan_applied")
        self.assertEqual(current.json()["plan_id"], applied["plan_id"])
        promised = {visit["ticket_id"]: visit for visit in current.json()["visits"]}
        self.assertEqual(len(promised), len(applied["assigned_ticket_ids"]))

        moved_ticket = min(promised)
        other_worker = max(visit["worker_id"] for visit in promised.values())
        second = self.publish_manual_edit(
            lambda visits: [
                {**visit, "worker_id": other_worker, "sequence": 9}
                if visit["ticket_id"] == moved_ticket
                else visit
                for visit in visits
            ]
        )
        self.assertEqual(second, first + 1)

        with Session(self.engine) as session:
            rows = session.scalars(
                select(DayPlanRevision)
                .where(DayPlanRevision.service_area_id == self.area_id)
                .order_by(DayPlanRevision.revision)
            ).all()
            # Exactly one revision of the area-day is current, and the partial unique
            # index would have refused a second one.
            self.assertEqual([row.is_current for row in rows], [False] * (len(rows) - 1) + [True])
            superseded = next(row for row in rows if row.revision == first)
            self.assertEqual(superseded.superseded_by_revision, second)
            self.assertIsNotNone(superseded.superseded_at)
            self.assertEqual(
                superseded.plan_state["visits"],
                [visit for visit in superseded.plan_state["visits"]],
            )
            self.assertEqual(
                {route.id: route.geojson for route in session.scalars(select(Route))},
                historical_geometry,
                "applying a later revision must not rewrite an earlier route snapshot",
            )

        historical = self.client.get(self.day_url(f"/revisions/{first}"), headers=self.headers)
        self.assertEqual(historical.status_code, 200, historical.text)
        self.assertFalse(historical.json()["is_current"])
        self.assertEqual(
            {visit["ticket_id"]: visit["worker_id"] for visit in historical.json()["visits"]},
            {ticket_id: visit["worker_id"] for ticket_id, visit in promised.items()},
        )

        listed = self.client.get(self.day_url("/revisions"), headers=self.headers)
        # The fixture day already carries a revision, so only the tail is ours.
        self.assertEqual([row["revision"] for row in listed.json()][-2:], [first, second])
        self.assertEqual(
            [row["reason"] for row in listed.json()][-2:], ["plan_applied", "manual_edit"]
        )

    def test_diff_of_the_current_revision_names_the_moved_visit(self):
        self.apply(self.preview(allow_partial=False))
        current = self.client.get(self.day_url("/current"), headers=self.headers).json()
        moved_ticket = min(visit["ticket_id"] for visit in current["visits"])
        other_worker = max(visit["worker_id"] for visit in current["visits"])
        previous_worker = next(
            visit["worker_id"] for visit in current["visits"] if visit["ticket_id"] == moved_ticket
        )
        self.publish_manual_edit(
            lambda visits: (
                [visit for visit in visits if visit["ticket_id"] != moved_ticket]
                + [
                    {
                        **next(v for v in visits if v["ticket_id"] == moved_ticket),
                        "worker_id": other_worker,
                    }
                ]
            )
        )
        diff = self.client.get(self.day_url("/diff"), headers=self.headers)
        self.assertEqual(diff.status_code, 200, diff.text)
        body = diff.json()
        self.assertEqual(body["from_revision"], current["revision"])
        self.assertEqual(body["to_revision"], current["revision"] + 1)
        self.assertEqual(body["reason"], "manual_edit")
        self.assertTrue(body["is_current"])
        self.assertEqual(body["added"], [])
        self.assertEqual(body["removed"], [])
        if previous_worker != other_worker:
            self.assertEqual(
                [item["ticket_id"] for item in body["changed"]],
                [moved_ticket],
            )
            self.assertEqual(
                body["changed"][0]["changes"]["worker_id"],
                {"from": previous_worker, "to": other_worker},
            )

    def test_routes_say_which_revision_they_belong_to(self):
        self.apply(self.preview(allow_partial=False))
        routes = self.client.get("/api/v1/routes", headers=self.headers)
        self.assertEqual(routes.status_code, 200, routes.text)
        body = routes.json()
        self.assertTrue(body)
        for route in body:
            self.assertEqual(route["service_area_id"], self.area_id)
            self.assertTrue(route["is_current_plan"])

        self.publish_manual_edit(lambda visits: visits)
        stale = self.client.get("/api/v1/routes", headers=self.headers).json()
        for route in stale:
            self.assertFalse(
                route["is_current_plan"],
                "a route of a superseded revision must not look current",
            )

    def test_a_new_ticket_in_the_same_area_day_makes_the_proposal_stale(self):
        plan = self.preview(allow_partial=False)
        with Session(self.engine) as session:
            revisions_before = session.scalar(select(func.count()).select_from(DayPlanRevision))
        with Session(self.engine) as session, session.begin():
            sample = session.scalars(select(Ticket).order_by(Ticket.id).limit(1)).one()
            session.add(
                Ticket(
                    location_id=sample.location_id,
                    service_area_id=sample.service_area_id,
                    title="Авария, поступившая после расчёта",
                    category=sample.category,
                    work_type_id=sample.work_type_id,
                    status=sample.status,
                    lifecycle_state=sample.lifecycle_state,
                    received_at=sample.received_at,
                    visit_window_start=sample.visit_window_start,
                    visit_window_end=sample.visit_window_end,
                    estimated_duration_minutes=sample.estimated_duration_minutes,
                )
            )
        response = self.client.post(
            f"/api/v1/planning/plans/{plan['plan_id']}/apply", headers=self.headers
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "plan_stale")
        with Session(self.engine) as session:
            self.assertEqual(session.scalar(select(func.count(Route.id))), 0)
            self.assertEqual(
                session.scalar(select(func.count()).select_from(DayPlanRevision)),
                revisions_before,
                "a refused apply must not publish a revision",
            )

    def test_untouched_area_day_has_no_current_revision(self):
        response = self.client.get(
            f"/api/v1/planning/areas/{self.area_id}/2030-02-20/current", headers=self.headers
        )
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json()["detail"]["code"], "day_plan_not_found")

    def test_revision_history_is_observer_only(self):
        worker_headers = self.auth(9)
        for suffix in ("/revisions", "/current", "/diff"):
            response = self.client.get(self.day_url(suffix), headers=worker_headers)
            self.assertEqual(response.status_code, 403, f"{suffix}: {response.text}")

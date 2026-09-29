"""T09: one current day plan per service area, an immutable history and an exact diff.

Covers A19 (two revisions, unchanged historical geometry, precise diff, consumers see
the current one) and the A20 part about a proposal that the area-day has moved past.
"""

import copy
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import create_access_token
from app.db.models import DayPlanRevision, PlanningPlan, Route, ServiceArea, Ticket, TicketAppliance
from app.db.session import get_session
from app.main import app
from app.modules.data_exchange.formats import parse_file, serialize
from app.modules.data_exchange.service import import_data
from app.modules.execution.models import WorkEvent
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

    def create_ticket(
        self,
        title,
        *,
        brigade_id=None,
        appliance_office_id=None,
        category="emergency",
        window=None,
        response_deadline_at=None,
    ):
        window_start, window_end = window or (
            "2030-01-15T11:00:00+03:00",
            "2030-01-15T17:00:00+03:00",
        )
        response = self.client.post(
            "/api/v1/tickets",
            json={
                "location_id": self.receipt["id_map"]["locations"]["1"],
                "service_area_id": self.area_id,
                "title": title,
                "description": "Аварийная заявка для проверки остатка смены",
                "work_type_id": self.receipt["id_map"]["work_types"]["1"],
                "category": category,
                "priority": 1 if category == "emergency" else 3,
                "received_at": self.now.isoformat(),
                "response_deadline_at": response_deadline_at,
                "sla_deadline_at": "2030-01-15T18:00:00+03:00",
                "visit_window_start": window_start,
                "visit_window_end": window_end,
                "estimated_duration_minutes": 30,
            },
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 201, response.text)
        ticket = response.json()
        if brigade_id is not None:
            brigade_response = self.client.put(
                f"/api/v1/tickets/{ticket['id']}/brigade",
                json={"brigade_id": brigade_id},
                headers=self.headers,
            )
            self.assertEqual(brigade_response.status_code, 200, brigade_response.text)
        with Session(self.engine) as session, session.begin():
            session.add(
                TicketAppliance(
                    ticket_id=ticket["id"],
                    appliance_id=self.receipt["id_map"]["appliances"]["1"],
                    office_id=appliance_office_id or self.receipt["id_map"]["offices"]["1"],
                    quantity=1,
                )
            )
        return ticket

    def test_regular_ticket_uses_only_a_free_gap_and_preserves_published_visits(self):
        initial = self.apply(self.preview())
        before = self.client.get(self.day_url("/current"), headers=self.headers).json()
        previous = {visit["ticket_id"]: visit for visit in before["visits"]}
        regular = self.create_ticket(
            "Обычная заявка в свободном интервале",
            brigade_id=self.receipt["id_map"]["brigades"]["1"],
            category="repair",
            window=("2030-01-15T08:00:00+03:00", "2030-01-15T18:00:00+03:00"),
        )

        response = self.client.post(
            self.day_url("/replan/preview"),
            json={"base_day_revision": initial["day_revision"]},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 201, response.text)
        proposal = response.json()
        after_proposed = {visit["ticket_id"]: visit for visit in proposal["replan_diff"]["added"]}
        self.assertEqual(proposal["replan_diff"]["changed"], [])
        self.assertEqual(proposal["replan_diff"]["removed"], [])
        self.assertIn(regular["id"], after_proposed)

        applied = self.apply(proposal)
        self.assertEqual(applied["day_revision"], initial["day_revision"] + 1)
        current = self.client.get(self.day_url("/current"), headers=self.headers).json()
        actual = {visit["ticket_id"]: visit for visit in current["visits"]}
        self.assertIn(regular["id"], actual)
        for ticket_id, visit in previous.items():
            with self.subTest(ticket_id=ticket_id):
                self.assertEqual(actual[ticket_id]["worker_id"], visit["worker_id"])
                self.assertEqual(actual[ticket_id]["sequence"], visit["sequence"])
                self.assertEqual(actual[ticket_id]["service_start_at"], visit["service_start_at"])

    def test_regular_ticket_without_a_gap_leaves_current_revision_untouched(self):
        initial = self.apply(self.preview())
        before = self.client.get(self.day_url("/current"), headers=self.headers).json()
        existing_start = before["visits"][0]["service_start_at"]
        start = datetime.fromisoformat(existing_start)
        regular = self.create_ticket(
            "Обычная заявка без свободного интервала",
            category="repair",
            window=(start.isoformat(), (start + timedelta(minutes=1)).isoformat()),
        )

        response = self.client.post(
            self.day_url("/replan/preview"),
            json={"base_day_revision": initial["day_revision"]},
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn(
            response.json()["detail"]["code"],
            {"ordinary_insert_ticket_ineligible", "ordinary_insert_no_gap"},
        )
        current = self.client.get(self.day_url("/current"), headers=self.headers).json()
        self.assertEqual(current["revision"], initial["day_revision"])
        self.assertEqual(current["visits"], before["visits"])
        with Session(self.engine) as session:
            ticket = session.get(Ticket, regular["id"])
            self.assertIsNone(ticket.assigned_worker_id)

    def execution_event(
        self, ticket_id, event, revision, key, occurred_at, *, worker_id=None, location_id=None
    ):
        payload = {
            "expected_revision": revision,
            "occurred_at": occurred_at,
            "payload": {},
        }
        if worker_id is not None:
            payload["worker_id"] = worker_id
        if location_id is not None:
            payload["location_id"] = location_id
        response = self.client.post(
            f"/api/v1/tickets/{ticket_id}/{event}",
            json=payload,
            headers=self.headers | {"Idempotency-Key": key},
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

    def test_replan_preview_includes_new_emergency_and_apply_publishes_one_revision(self):
        initial = self.apply(self.preview())
        emergency = self.create_ticket(
            "Авария в течение смены", brigade_id=self.receipt["id_map"]["brigades"]["1"]
        )
        preview_response = self.client.post(
            self.day_url("/replan/preview"),
            json={"base_day_revision": initial["day_revision"]},
            headers=self.headers,
        )
        self.assertEqual(preview_response.status_code, 201, preview_response.text)
        proposal = preview_response.json()
        self.assertEqual(proposal["replan_diff"]["from_revision"], initial["day_revision"])
        self.assertIn(
            emergency["id"],
            [visit["ticket_id"] for visit in proposal["replan_diff"]["added"]],
            f"metrics={proposal['metrics']} unassigned={proposal['unassigned']}",
        )
        self.assertIn(
            emergency["id"],
            [stop["ticket_id"] for route in proposal["routes"] for stop in route["stops"]],
        )
        response_estimate = next(
            item
            for item in proposal["replan_diff"]["emergency_response"]
            if item["ticket_id"] == emergency["id"]
        )
        self.assertEqual(response_estimate["status"], "scheduled")
        self.assertEqual(
            datetime.fromisoformat(response_estimate["received_at"]),
            datetime.fromisoformat(emergency["received_at"]),
        )
        self.assertIsNotNone(response_estimate["reaction_to_arrival_minutes"])
        self.assertIsNotNone(response_estimate["reaction_to_service_start_minutes"])

        applied = self.apply(proposal)
        self.assertEqual(applied["day_revision"], initial["day_revision"] + 1)
        self.assertFalse(applied["already_applied"])
        current = self.client.get(self.day_url("/current"), headers=self.headers)
        self.assertEqual(current.status_code, 200, current.text)
        self.assertEqual(current.json()["reason"], "event_replan")
        self.assertIn(emergency["id"], [visit["ticket_id"] for visit in current.json()["visits"]])

        replay = self.apply(proposal)
        self.assertTrue(replay["already_applied"])
        self.assertEqual(replay["day_revision"], applied["day_revision"])

        stale_proposal = self.client.post(
            self.day_url("/replan/preview"),
            json={"base_day_revision": applied["day_revision"]},
            headers=self.headers,
        )
        self.assertEqual(stale_proposal.status_code, 201, stale_proposal.text)
        self.create_ticket("Вторая заявка после предпросмотра")
        stale_apply = self.client.post(
            f"/api/v1/planning/plans/{stale_proposal.json()['plan_id']}/apply",
            headers=self.headers,
        )
        self.assertEqual(stale_apply.status_code, 409, stale_apply.text)
        self.assertEqual(stale_apply.json()["detail"]["code"], "plan_stale")

    def test_replan_requires_a_current_day_revision_and_uses_its_endpoint(self):
        generic = self.client.post(
            "/api/v1/planning/preview",
            json={"route_date": "2030-02-20", "replan": True},
            headers=self.headers,
        )
        self.assertEqual(generic.status_code, 422, generic.text)
        self.assertEqual(generic.json()["detail"]["code"], "replan_endpoint_required")

        missing_plan = self.client.post(
            f"/api/v1/planning/areas/{self.area_id}/2030-02-20/replan/preview",
            json={},
            headers=self.headers,
        )
        self.assertEqual(missing_plan.status_code, 404, missing_plan.text)
        self.assertEqual(missing_plan.json()["detail"]["code"], "day_plan_not_found")

    def test_window_experiment_compares_plans_without_persisting_or_changing_live_data(self):
        initial = self.apply(self.preview())
        current = self.client.get(self.day_url("/current"), headers=self.headers).json()
        ticket_id = current["visits"][0]["ticket_id"]
        with Session(self.engine) as session:
            ticket = session.get(Ticket, ticket_id)
            original_start = ticket.visit_window_start
            original_end = ticket.visit_window_end
            plans_before = session.scalar(select(func.count()).select_from(PlanningPlan))

        response = self.client.post(
            self.day_url("/window-experiment"),
            json={
                "base_day_revision": initial["day_revision"],
                "allow_partial": True,
                "windows": [
                    {
                        "ticket_id": ticket_id,
                        "visit_window_start": "2030-01-15T00:00:00+03:00",
                        "visit_window_end": "2030-01-15T23:59:00+03:00",
                    }
                ],
            },
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertTrue(result["experimental"])
        self.assertFalse(result["applied"])
        self.assertEqual(result["base_day_revision"], initial["day_revision"])
        self.assertIn("metrics", result["baseline"])
        self.assertIn("metrics", result["experiment"])
        self.assertNotIn("plan_id", result["experiment"])
        with Session(self.engine) as session:
            ticket = session.get(Ticket, ticket_id)
            plans_after = session.scalar(select(func.count()).select_from(PlanningPlan))
            current_revision = session.scalar(
                select(DayPlanRevision.revision).where(
                    DayPlanRevision.service_area_id == self.area_id,
                    DayPlanRevision.route_date == ROUTE_DATE,
                    DayPlanRevision.is_current.is_(True),
                )
            )
        self.assertEqual(ticket.visit_window_start, original_start)
        self.assertEqual(ticket.visit_window_end, original_end)
        self.assertEqual(plans_after, plans_before)
        self.assertEqual(current_revision, initial["day_revision"])

    def test_empty_replan_unassigns_pending_tickets_without_cancelling_them(self):
        initial = self.apply(self.preview())
        with Session(self.engine) as session, session.begin():
            session.execute(text("UPDATE workers SET is_on_line = false"))

        preview_response = self.client.post(
            self.day_url("/replan/preview"),
            json={"base_day_revision": initial["day_revision"]},
            headers=self.headers,
        )
        self.assertEqual(preview_response.status_code, 201, preview_response.text)
        proposal = preview_response.json()
        self.assertEqual(proposal["routes"], [])
        self.assertEqual(
            proposal["outcome"],
            "partial",
            f"metrics={proposal['metrics']} unassigned={proposal['unassigned']}",
        )

        applied = self.apply(proposal)
        self.assertEqual(applied["assigned_ticket_ids"], [])
        with Session(self.engine) as session:
            rows = session.execute(
                text("SELECT lifecycle_state, status, assigned_worker_id FROM tickets ORDER BY id")
            ).all()
            unassign_events = session.scalar(
                text("SELECT count(*) FROM work_events WHERE event_type = 'unassign'")
            )
        self.assertEqual(rows, [("waiting_assignment", "planned", None)] * len(rows))
        self.assertEqual(unassign_events, len(rows))

    def test_cancelled_in_flight_ticket_is_removed_while_worker_leg_is_preserved(self):
        initial = self.apply(self.preview())
        previous = self.client.get(self.day_url("/current"), headers=self.headers).json()
        active_visit = previous["visits"][0]
        ticket_id = active_visit["ticket_id"]
        worker_id = active_visit["worker_id"]
        with Session(self.engine) as session:
            ticket = session.get(Ticket, ticket_id)
            ticket_revision = ticket.revision
            destination_id = ticket.location_id
        source_id = self.receipt["id_map"]["locations"]["1"]

        dispatched = self.execution_event(
            ticket_id,
            "dispatch",
            ticket_revision,
            "planner-cancel-dispatch",
            "2030-01-15T09:00:00+03:00",
        )
        en_route = self.execution_event(
            ticket_id,
            "start-route",
            dispatched["revision"],
            "planner-cancel-route",
            "2030-01-15T09:05:00+03:00",
            worker_id=worker_id,
            location_id=source_id,
        )
        cancelled = self.client.post(
            f"/api/v1/tickets/{ticket_id}/cancel",
            json={
                "expected_revision": en_route["revision"],
                "occurred_at": "2030-01-15T09:10:00+03:00",
                "expected_available_at": "2030-01-15T11:00:00+03:00",
                "reason": "Клиент отменил заявку после выезда",
                "payload": {},
            },
            headers=self.headers | {"Idempotency-Key": "planner-cancel-in-flight"},
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()["state"], "cancelled")

        self.now = self.now.replace(day=15, hour=6, minute=15)
        day_state = self.client.get(
            f"/api/v1/workers/{worker_id}/day-state",
            params={
                "service_area_id": self.area_id,
                "date": ROUTE_DATE.isoformat(),
                "at": self.now.isoformat(),
            },
            headers=self.headers,
        )
        self.assertEqual(day_state.status_code, 200, day_state.text)
        self.assertEqual(day_state.json()["current_ticket_id"], ticket_id)
        self.assertEqual(day_state.json()["current_destination_id"], destination_id)
        self.assertEqual(
            datetime.fromisoformat(day_state.json()["expected_available_at"]),
            datetime.fromisoformat("2030-01-15T11:00:00+03:00"),
        )
        response = self.client.post(
            self.day_url("/replan/preview"),
            json={"base_day_revision": initial["day_revision"]},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 201, response.text)
        proposal = response.json()
        self.assertIn(
            ticket_id,
            [visit["ticket_id"] for visit in proposal["replan_diff"]["removed"]],
        )
        self.assertNotIn(
            ticket_id,
            [stop["ticket_id"] for route in proposal["routes"] for stop in route["stops"]],
        )
        worker_route = next(
            route for route in proposal["routes"] if route["worker_id"] == worker_id
        )
        self.assertEqual(worker_route["start_location_id"], destination_id)
        self.assertGreaterEqual(
            datetime.fromisoformat(worker_route["departure_at"]),
            datetime.fromisoformat("2030-01-15T11:00:00+03:00"),
        )

        applied = self.apply(proposal)
        self.assertEqual(applied["day_revision"], initial["day_revision"] + 1)
        current = self.client.get(self.day_url("/current"), headers=self.headers).json()
        self.assertNotIn(ticket_id, [visit["ticket_id"] for visit in current["visits"]])
        original = self.client.get(
            self.day_url(f"/revisions/{initial['day_revision']}"), headers=self.headers
        )
        self.assertEqual(original.status_code, 200, original.text)
        self.assertIn(ticket_id, [visit["ticket_id"] for visit in original.json()["visits"]])

    def test_midday_replan_keeps_completed_visit_and_uses_confirmed_location_and_time(self):
        initial = self.apply(self.preview())
        day_state = self.client.get(self.day_url("/current"), headers=self.headers).json()
        visits = sorted(day_state["visits"], key=lambda visit: visit["service_start_at"])
        completed_visit = visits[0]
        ticket_id = completed_visit["ticket_id"]
        worker_id = completed_visit["worker_id"]
        with Session(self.engine) as session:
            ticket = session.get(Ticket, ticket_id)
            destination_id = ticket.location_id
            source_id = self.receipt["id_map"]["locations"]["1"]
            ticket_revision = ticket.revision

        event = self.execution_event(
            ticket_id,
            "dispatch",
            ticket_revision,
            "t06-midday-dispatch",
            "2030-01-15T09:00:00+03:00",
        )
        event = self.execution_event(
            ticket_id,
            "start-route",
            event["revision"],
            "t06-midday-route",
            "2030-01-15T09:05:00+03:00",
            worker_id=worker_id,
            location_id=source_id,
        )
        event = self.execution_event(
            ticket_id,
            "start",
            event["revision"],
            "t06-midday-start",
            "2030-01-15T09:30:00+03:00",
            worker_id=worker_id,
            location_id=destination_id,
        )
        self.execution_event(
            ticket_id,
            "complete",
            event["revision"],
            "t06-midday-complete",
            "2030-01-15T10:00:00+03:00",
            worker_id=worker_id,
            location_id=destination_id,
        )

        self.now = self.now.replace(day=15, hour=7, minute=15)
        emergency = self.create_ticket(
            "Авария после завершённого выезда",
            brigade_id=self.receipt["id_map"]["brigades"]["1"],
        )
        preview_response = self.event_preview(
            emergency["id"], base_day_revision=initial["day_revision"]
        )
        self.assertEqual(preview_response.status_code, 201, preview_response.text)
        emergency_preview = preview_response.json()
        event_result = emergency_preview["event"]
        proposal = emergency_preview["plan"]
        self.assertTrue(event_result["can_apply"])
        self.assertEqual(event_result["selection_reason"]["code"], "emergency_response_priority")
        self.assertEqual(
            event_result["selection_reason"]["selected_worker_id"],
            event_result["selected_slot"]["worker_id"],
        )
        self.assertEqual(event_result["sla_forecast"]["response_target_minutes"], 120)
        self.assertTrue(event_result["sla_forecast"]["response_deadline_met"])
        self.assertEqual(
            datetime.fromisoformat(event_result["sla_forecast"]["response_deadline_at"]),
            datetime.fromisoformat(emergency["response_deadline_at"]),
        )
        self.assertEqual(
            datetime.fromisoformat(event_result["sla_forecast"]["visit_window_start"]),
            datetime.fromisoformat(emergency["visit_window_start"]),
        )
        self.assertEqual(
            datetime.fromisoformat(event_result["sla_forecast"]["visit_window_end"]),
            datetime.fromisoformat(emergency["visit_window_end"]),
        )
        self.assertEqual(proposal["metrics"]["available_workers"], 4)
        self.assertIn(
            emergency["id"],
            [visit["ticket_id"] for visit in proposal["replan_diff"]["added"]],
        )
        self.assertIn(
            ticket_id,
            proposal["replan_diff"]["unchanged_ticket_ids"],
            "a confirmed completed visit remains in the published day plan",
        )
        self.assertTrue(
            all(
                datetime.fromisoformat(visit["service_start_at"])
                >= datetime.fromisoformat("2030-01-15T10:15:00+03:00")
                for route in proposal["routes"]
                for visit in route["stops"]
            )
        )
        self.assertEqual(proposal["replan_diff"]["ticket_event"]["ticket_id"], emergency["id"])
        self.assertTrue(proposal["replan_diff"]["emergency_sla_forecasts"])
        before_apply = self.client.get(self.day_url("/current"), headers=self.headers).json()
        self.assertEqual(before_apply["revision"], initial["day_revision"])

        applied = self.apply(proposal)
        current = self.client.get(self.day_url("/current"), headers=self.headers).json()
        published = {visit["ticket_id"]: visit for visit in current["visits"]}
        self.assertEqual(applied["day_revision"], initial["day_revision"] + 1)
        self.assertIn(ticket_id, published)
        self.assertEqual(published[ticket_id]["service_end_at"], completed_visit["service_end_at"])
        self.assertIn(emergency["id"], published)

    def test_progress_delay_keeps_started_visit_and_reschedules_workers_remainder(self):
        initial = self.apply(self.preview())
        current = self.client.get(self.day_url("/current"), headers=self.headers).json()
        active_visit = current["visits"][0]
        ticket_id = active_visit["ticket_id"]
        worker_id = active_visit["worker_id"]
        with Session(self.engine) as session:
            ticket = session.get(Ticket, ticket_id)
            ticket_revision = ticket.revision
            destination_id = ticket.location_id
        source_id = self.receipt["id_map"]["locations"]["1"]

        dispatched = self.execution_event(
            ticket_id,
            "dispatch",
            ticket_revision,
            "planner-delay-dispatch",
            "2030-01-15T09:00:00+03:00",
        )
        en_route = self.execution_event(
            ticket_id,
            "start-route",
            dispatched["revision"],
            "planner-delay-route",
            "2030-01-15T09:05:00+03:00",
            worker_id=worker_id,
            location_id=source_id,
        )
        started = self.execution_event(
            ticket_id,
            "start",
            en_route["revision"],
            "planner-delay-start",
            "2030-01-15T09:30:00+03:00",
            worker_id=worker_id,
            location_id=destination_id,
        )
        delayed = self.client.post(
            f"/api/v1/tickets/{ticket_id}/delay",
            json={
                "expected_revision": started["revision"],
                "occurred_at": "2030-01-15T10:00:00+03:00",
                "expected_available_at": "2030-01-15T12:00:00+03:00",
                "reason": "Работа займёт ещё два часа",
                "payload": {},
            },
            headers=self.headers | {"Idempotency-Key": "planner-delay-active"},
        )
        self.assertEqual(delayed.status_code, 200, delayed.text)
        self.assertEqual(delayed.json()["state"], "in_progress")

        self.now = self.now.replace(day=15, hour=7, minute=15)
        with Session(self.engine) as session:
            eligible_team = session.execute(
                text(
                    """
                    SELECT member.brigade_id, brigade.office_id
                    FROM brigade_members AS member
                    JOIN brigades AS brigade ON brigade.id = member.brigade_id
                    WHERE member.worker_id <> :active_worker_id
                    ORDER BY member.worker_id
                    LIMIT 1
                    """
                ),
                {"active_worker_id": worker_id},
            ).one()
        emergency = self.create_ticket(
            "Авария после задержки",
            brigade_id=eligible_team.brigade_id,
            appliance_office_id=eligible_team.office_id,
        )
        response = self.client.post(
            self.day_url("/replan/preview"),
            json={"base_day_revision": initial["day_revision"]},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 201, response.text)
        proposal = response.json()
        self.assertIn(ticket_id, proposal["replan_diff"]["unchanged_ticket_ids"])
        self.assertIn(
            emergency["id"],
            [item["ticket_id"] for item in proposal["replan_diff"]["added"]],
            f"metrics={proposal['metrics']} unassigned={proposal['unassigned']}",
        )
        self.assertNotIn(
            worker_id,
            [route["worker_id"] for route in proposal["routes"]],
            "an ETA is informative but not a confirmed safe point for a new route",
        )
        excluded = next(
            worker for worker in proposal["excluded_workers"] if worker["worker_id"] == worker_id
        )
        self.assertEqual(excluded["reason"]["code"], "active_stage_not_completed")
        response_estimate = next(
            item
            for item in proposal["replan_diff"]["emergency_response"]
            if item["ticket_id"] == emergency["id"]
        )
        self.assertEqual(
            datetime.fromisoformat(response_estimate["received_at"]),
            datetime.fromisoformat(emergency["received_at"]),
        )

        applied = self.apply(proposal)
        self.assertEqual(applied["day_revision"], initial["day_revision"] + 1)
        published = self.client.get(self.day_url("/current"), headers=self.headers).json()
        self.assertEqual(
            next(visit for visit in published["visits"] if visit["ticket_id"] == ticket_id),
            active_visit,
        )
        self.assertIn(emergency["id"], [visit["ticket_id"] for visit in published["visits"]])

    def test_replan_apply_rejects_a_route_whose_departure_time_has_passed(self):
        initial = self.apply(self.preview())
        self.now = self.now.replace(day=15, hour=7, minute=15)
        response = self.client.post(
            self.day_url("/replan/preview"),
            json={"base_day_revision": initial["day_revision"]},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 201, response.text)
        proposal = response.json()
        departures = [datetime.fromisoformat(route["departure_at"]) for route in proposal["routes"]]
        self.assertTrue(departures)
        first_departure = min(departures)
        self.assertGreaterEqual(first_departure, self.now)
        self.assertLess(first_departure, self.now + timedelta(minutes=5))

        self.now = first_departure + timedelta(seconds=1)
        stale = self.client.post(
            f"/api/v1/planning/plans/{proposal['plan_id']}/apply", headers=self.headers
        )
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(stale.json()["detail"]["code"], "plan_stale")
        self.assertEqual(
            stale.json()["detail"]["reason"],
            "replan_departure_elapsed",
        )
        current = self.client.get(self.day_url("/current"), headers=self.headers)
        self.assertEqual(current.json()["revision"], initial["day_revision"])

    def test_replan_returns_timed_unavailable_worker_after_dispatcher_eta(self):
        initial = self.apply(self.preview())
        worker_id = self.payload["worker_ids"][0]
        self.now = self.now.replace(day=15, hour=7, minute=15)
        with Session(self.engine) as session, session.begin():
            session.execute(text("UPDATE workers SET is_on_line = false"))

        unavailable = self.client.post(
            f"/api/v1/workers/{worker_id}/unavailable",
            json={
                "expected_revision": 1,
                "service_area_id": self.area_id,
                "route_date": ROUTE_DATE.isoformat(),
                "occurred_at": "2030-01-15T10:15:00+03:00",
                "expected_available_at": "2030-01-15T11:00:00+03:00",
                "worker_id": worker_id,
                "reason": "Инженер вернётся через сорок пять минут",
                "payload": {},
            },
            headers=self.headers | {"Idempotency-Key": "t06-worker-return-eta"},
        )
        self.assertEqual(unavailable.status_code, 200, unavailable.text)
        emergency = self.create_ticket(
            "Авария к возвращению инженера",
            brigade_id=self.receipt["id_map"]["brigades"]["1"],
        )
        preview_response = self.client.post(
            self.day_url("/replan/preview"),
            json={"base_day_revision": initial["day_revision"]},
            headers=self.headers,
        )
        self.assertEqual(preview_response.status_code, 201, preview_response.text)
        proposal = preview_response.json()
        self.assertEqual(proposal["metrics"]["available_workers"], 1)
        self.assertIn(
            emergency["id"],
            [stop["ticket_id"] for route in proposal["routes"] for stop in route["stops"]],
        )
        self.assertTrue(proposal["routes"])
        self.assertEqual({route["worker_id"] for route in proposal["routes"]}, {worker_id})
        self.assertTrue(
            all(
                datetime.fromisoformat(stop["service_start_at"])
                >= datetime.fromisoformat("2030-01-15T11:00:00+03:00")
                for route in proposal["routes"]
                for stop in route["stops"]
            )
        )

        applied = self.apply(proposal)
        self.assertIn(emergency["id"], applied["assigned_ticket_ids"])

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

    def event_preview(self, ticket_id, **payload):
        return self.client.post(
            f"{self.day_url()}/tickets/{ticket_id}/preview",
            json=payload,
            headers=self.headers,
        )

    def test_ticket_event_preview_rejects_client_selected_policy(self):
        initial = self.apply(self.preview())
        ticket = self.create_ticket(
            "Обычная заявка с попыткой выбрать режим",
            category="repair",
            window=("2030-01-15T08:00:00+03:00", "2030-01-15T18:00:00+03:00"),
        )

        response = self.event_preview(
            ticket["id"], base_day_revision=initial["day_revision"], mode="emergency"
        )

        self.assertEqual(response.status_code, 422, response.text)

    def test_ticket_event_preview_rejects_stale_revision_without_saving_a_plan(self):
        initial = self.apply(self.preview())
        ticket = self.create_ticket(
            "Авария с устаревшей ревизией",
            category="emergency",
            brigade_id=self.receipt["id_map"]["brigades"]["1"],
        )
        with Session(self.engine) as session:
            plans_before = session.scalar(select(func.count()).select_from(PlanningPlan))

        response = self.event_preview(ticket["id"], base_day_revision=initial["day_revision"] + 1)

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "day_revision_stale")
        with Session(self.engine) as session:
            plans_after = session.scalar(select(func.count()).select_from(PlanningPlan))
        self.assertEqual(plans_after, plans_before)

    def test_regular_ticket_event_uses_slot_preview_and_publishes_linked_revision(self):
        initial = self.apply(self.preview())
        before = self.client.get(self.day_url("/current"), headers=self.headers).json()
        previous = {visit["ticket_id"]: visit for visit in before["visits"]}
        ticket = self.create_ticket(
            "Обычная заявка через поиск слота",
            category="repair",
            brigade_id=self.receipt["id_map"]["brigades"]["1"],
            window=("2030-01-15T08:00:00+03:00", "2030-01-15T18:00:00+03:00"),
        )

        response = self.event_preview(ticket["id"], base_day_revision=initial["day_revision"])

        self.assertEqual(response.status_code, 201, response.text)
        preview = response.json()
        self.assertEqual(preview["event"]["category"], "repair")
        self.assertEqual(preview["event"]["outcome"], "insertion_ready", preview["event"])
        self.assertEqual(
            datetime.fromisoformat(preview["event"]["received_at"]),
            datetime.fromisoformat(ticket["received_at"]),
        )
        self.assertEqual(
            preview["plan"]["replan_diff"]["ticket_event"]["source_event_id"],
            preview["event"]["source_event_id"],
        )
        self.assertIn(
            preview["event"]["selected_slot"]["worker_id"],
            {visit["worker_id"] for visit in before["visits"]},
        )
        self.assertGreaterEqual(preview["event"]["road_contribution"]["added_travel_minutes"], 0)
        plan = preview["plan"]
        applied = self.apply(plan)

        self.assertEqual(applied["day_revision"], initial["day_revision"] + 1)
        current = self.client.get(self.day_url("/current"), headers=self.headers).json()
        self.assertEqual(current["reason"], "ticket_inserted")
        actual = {visit["ticket_id"]: visit for visit in current["visits"]}
        self.assertIn(ticket["id"], actual)
        expected_shifted = sorted(
            ticket_id
            for ticket_id, visit in previous.items()
            if actual[ticket_id]["sequence"] != visit["sequence"]
            or actual[ticket_id]["service_start_at"] != visit["service_start_at"]
        )
        self.assertEqual(preview["event"]["shifted_ticket_ids"], expected_shifted)
        for ticket_id, visit in previous.items():
            self.assertEqual(actual[ticket_id]["worker_id"], visit["worker_id"])
        for worker_id in {visit["worker_id"] for visit in previous.values()}:
            previous_order = [
                ticket_id
                for ticket_id, _ in sorted(previous.items(), key=lambda item: item[1]["sequence"])
                if previous[ticket_id]["worker_id"] == worker_id
            ]
            current_order = [
                visit["ticket_id"]
                for visit in sorted(
                    (visit for visit in current["visits"] if visit["worker_id"] == worker_id),
                    key=lambda visit: visit["sequence"],
                )
                if visit["ticket_id"] in previous
            ]
            self.assertEqual(current_order, previous_order)

        with Session(self.engine) as session:
            revision = session.scalar(
                select(DayPlanRevision).where(
                    DayPlanRevision.service_area_id == self.area_id,
                    DayPlanRevision.route_date == ROUTE_DATE,
                    DayPlanRevision.is_current.is_(True),
                )
            )
            source_event = session.get(WorkEvent, revision.event_id)
            self.assertEqual(revision.event_id, preview["event"]["source_event_id"])
            self.assertEqual(source_event.event_type.value, "new_ticket")
            self.assertEqual(source_event.ticket_id, ticket["id"])

    def test_regular_ticket_without_slot_is_explained_without_mutating_day(self):
        initial = self.apply(self.preview())
        before = self.client.get(self.day_url("/current"), headers=self.headers).json()
        ticket = self.create_ticket(
            "Обычная заявка без слота",
            category="repair",
            brigade_id=self.receipt["id_map"]["brigades"]["1"],
            window=("2030-01-15T01:00:00+03:00", "2030-01-15T01:01:00+03:00"),
        )

        response = self.event_preview(ticket["id"], base_day_revision=initial["day_revision"])

        self.assertEqual(response.status_code, 201, response.text)
        preview = response.json()
        self.assertEqual(preview["event"]["outcome"], "not_insertable")
        self.assertIsNone(preview["plan"])
        self.assertTrue(preview["event"]["candidate_reasons"])
        current = self.client.get(self.day_url("/current"), headers=self.headers).json()
        self.assertEqual(current["revision"], initial["day_revision"])
        self.assertEqual(current["visits"], before["visits"])

    def test_non_applicable_emergency_preview_cannot_be_applied(self):
        initial = self.apply(self.preview())
        before = self.client.get(self.day_url("/current"), headers=self.headers).json()
        ticket = self.create_ticket(
            "Авария вне смены не должна публиковаться",
            brigade_id=self.receipt["id_map"]["brigades"]["1"],
            window=("2030-01-15T01:00:00+03:00", "2030-01-15T01:01:00+03:00"),
        )

        preview_response = self.event_preview(
            ticket["id"], base_day_revision=initial["day_revision"]
        )

        self.assertEqual(preview_response.status_code, 201, preview_response.text)
        preview = preview_response.json()
        self.assertEqual(preview["event"]["outcome"], "emergency_unassigned")
        self.assertFalse(preview["event"]["can_apply"])
        self.assertEqual(preview["event"]["sla_forecast"]["response_sla_status"], "unassigned")
        self.assertFalse(preview["event"]["sla_forecast"]["response_deadline_met"])
        apply_response = self.client.post(
            f"/api/v1/planning/plans/{preview['plan']['plan_id']}/apply",
            headers=self.headers,
        )
        self.assertEqual(apply_response.status_code, 409, apply_response.text)
        self.assertEqual(
            apply_response.json()["detail"]["code"], "ticket_event_preview_not_applicable"
        )
        current = self.client.get(self.day_url("/current"), headers=self.headers).json()
        self.assertEqual(current["revision"], initial["day_revision"])
        self.assertEqual(current["visits"], before["visits"])

    def test_emergency_event_uses_replan_and_apply_records_its_new_ticket_event(self):
        initial = self.apply(self.preview())
        ticket = self.create_ticket(
            "Авария через диспетчерский event API",
            brigade_id=self.receipt["id_map"]["brigades"]["1"],
        )

        response = self.event_preview(ticket["id"], base_day_revision=initial["day_revision"])

        self.assertEqual(response.status_code, 201, response.text)
        preview = response.json()
        self.assertEqual(preview["event"]["category"], "emergency")
        self.assertEqual(preview["plan"]["replan_diff"]["ticket_event"]["event_type"], "new_ticket")
        self.assertIn(
            preview["event"]["outcome"],
            {"emergency_replan_ready", "sla_risk", "sla_violation"},
        )
        self.assertEqual(preview["event"]["ticket_id"], ticket["id"])
        self.assertIsNotNone(preview["event"]["sla_forecast"])
        self.assertEqual(preview["event"]["sla_forecast"]["response_target_minutes"], 120)
        self.assertIsInstance(preview["event"]["sla_forecast"]["response_deadline_met"], bool)
        self.assertEqual(
            preview["event"]["selection_reason"]["code"], "emergency_response_priority"
        )

        applied = self.apply(preview["plan"])

        current = self.client.get(self.day_url("/current"), headers=self.headers).json()
        self.assertEqual(current["reason"], "emergency_replan")
        self.assertIn(ticket["id"], {visit["ticket_id"] for visit in current["visits"]})
        with Session(self.engine) as session:
            revision = session.scalar(
                select(DayPlanRevision).where(
                    DayPlanRevision.service_area_id == self.area_id,
                    DayPlanRevision.route_date == ROUTE_DATE,
                    DayPlanRevision.is_current.is_(True),
                )
            )
            source_event = session.get(WorkEvent, revision.event_id)
            self.assertEqual(revision.event_id, preview["event"]["source_event_id"])
            self.assertEqual(source_event.event_type.value, "new_ticket")
            self.assertEqual(source_event.ticket_id, ticket["id"])
        self.assertEqual(applied["day_revision"], initial["day_revision"] + 1)

    def test_60_minute_response_target_missed_due_to_customer_window_is_explicit(self):
        initial = self.apply(self.preview())
        ticket = self.create_ticket(
            "Авария с окном позже 60-минутного норматива",
            response_deadline_at=(self.now + timedelta(minutes=60)).isoformat(),
            window=("2030-01-15T11:00:00+03:00", "2030-01-15T17:00:00+03:00"),
        )

        response = self.event_preview(ticket["id"], base_day_revision=initial["day_revision"])

        self.assertEqual(response.status_code, 201, response.text)
        preview = response.json()
        self.assertFalse(preview["event"]["can_apply"])
        self.assertEqual(preview["event"]["outcome"], "emergency_unassigned")
        forecast = preview["event"]["sla_forecast"]
        self.assertEqual(forecast["response_target_minutes"], 60)
        self.assertFalse(forecast["response_deadline_met"])
        self.assertEqual(forecast["response_sla_status"], "unassigned")
        self.assertIsNotNone(forecast["unassigned_reason"])
        self.assertEqual(
            datetime.fromisoformat(forecast["visit_window_start"]),
            datetime.fromisoformat(ticket["visit_window_start"]),
        )
        current = self.client.get(self.day_url("/current"), headers=self.headers).json()
        self.assertEqual(current["revision"], initial["day_revision"])

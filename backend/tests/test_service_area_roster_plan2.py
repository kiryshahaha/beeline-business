"""Plan 2: the service area is the only territorial boundary; a day keeps its roster.

Unit tests cover the single area resolver and the planner's refusal to borrow the area
of a request. PostgreSQL tests cover every assignment path and the published roster:
the first plan admits every selected engineer, a replan never adds anyone, an explicit
dispatcher action is recorded, and legacy revisions are rebuilt only from their own
planning snapshots.
"""

import unittest
from datetime import datetime, time
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import create_access_token
from app.db.models import (
    BrigadeMember,
    Building,
    City,
    DayPlanRevision,
    Location,
    PlanningPlan,
    ServiceArea,
    Street,
    TicketAppliance,
    Worker,
)
from app.db.session import get_session
from app.main import app
from app.modules.data_exchange.formats import parse_file, serialize
from app.modules.data_exchange.service import import_data
from app.modules.planning import router as api
from app.modules.planning.eligibility import check_eligibility
from app.modules.service_areas.resolve import (
    MISMATCH,
    MISSING,
    ServiceAreaResolutionError,
    resolve_area,
    worker_signals,
)
from app.modules.tickets import router as tickets_api
from planning_scenarios import NOW, ROUTE_DATE, generate_planning_dataset
from tests.planning_fakes import FeasiblePlanner, provider_factory
from tests.support import CommittedDatabaseTestCase

MOSCOW = ZoneInfo("Europe/Moscow")
EPOCH = datetime(2030, 1, 15, tzinfo=MOSCOW)


class ResolveAreaTests(unittest.TestCase):
    def test_one_stated_area_is_the_area(self):
        self.assertEqual(resolve_area("worker", 1, worker_signals(None, brigade=7)), 7)

    def test_agreeing_sources_resolve_to_their_area(self):
        signals = worker_signals(7, brigade=7, brigade_office=7, stock_office=7)
        self.assertEqual(resolve_area("worker", 1, signals), 7)

    def test_no_source_is_missing_never_a_default(self):
        with self.assertRaises(ServiceAreaResolutionError) as raised:
            resolve_area("worker", 5, worker_signals(None))
        self.assertEqual(raised.exception.code, MISSING)
        self.assertEqual(raised.exception.subject_id, 5)

    def test_contradicting_sources_name_every_source_instead_of_picking_one(self):
        with self.assertRaises(ServiceAreaResolutionError) as raised:
            resolve_area("worker", 5, worker_signals(7, brigade=8, stock_office=7))
        self.assertEqual(raised.exception.code, MISMATCH)
        self.assertEqual(raised.exception.sources, {"brigade": 8, "stock_office": 7, "worker": 7})


class EligibilityWithoutAreaFallbackTests(unittest.TestCase):
    def snapshot(self, **overrides):
        snapshot = {
            "policy_version": 1,
            "request": {"route_date": "2030-01-15", "ticket_ids": [1], "worker_ids": [10]},
            "service_area_id": 1,
            "workers": [
                {
                    "user_id": 10,
                    "workshift_start": "09:00:00",
                    "workshift_end": "18:00:00",
                    "transport_type": "car",
                    "is_on_line": True,
                    "service_area_id": None,
                    "stock_office_id": 1,
                }
            ],
            "brigades": [],
            "members": [],
            "offices": [{"id": 1, "location_id": 10}],
            "locations": [
                {"id": 10, "latitude": 55.75, "longitude": 37.65},
                {"id": 50, "latitude": 55.72, "longitude": 37.62},
            ],
            "roles": [{"id": 10, "role": "worker"}],
            "skills": [{"worker_id": 10, "skill_id": 1}],
            "busy_tickets": [],
            "assignments": [],
            "allocations": [],
            "required_skills": [{"work_type_id": 1, "skill_id": 1}],
            "required_appliances": [],
            "appliances": [],
            "stocks": [],
            "reservations": [],
            "tickets": [
                {
                    "id": 1,
                    "location_id": 50,
                    "work_type_id": 1,
                    "service_area_id": 1,
                    "status": "planned",
                    "visit_window_start": "2030-01-15T09:00:00+03:00",
                    "visit_window_end": "2030-01-15T18:00:00+03:00",
                }
            ],
            "work_types": [
                {
                    "id": 1,
                    "name": "Монтаж",
                    "work_minutes": 50,
                    "documents_minutes": 10,
                    "default_priority": 3,
                    "category": "installation",
                }
            ],
            "rules": [{"work_type_id": 1, "service_duration_source": "work_plus_documents"}],
        }
        return snapshot | overrides

    def test_worker_without_resolved_area_is_excluded_not_given_the_plan_area(self):
        prepared = check_eligibility(self.snapshot(worker_service_areas={}), EPOCH)
        self.assertEqual(prepared["workers"], [])
        self.assertEqual(prepared["excluded_workers"][0]["reason"]["code"], MISSING)
        self.assertEqual(prepared["unassigned"][0]["ticket_id"], 1)

    def test_normalized_string_keys_still_resolve_the_worker_area(self):
        prepared = check_eligibility(self.snapshot(worker_service_areas={"10": 1}), EPOCH)
        self.assertEqual([w["user_id"] for w in prepared["workers"]], [10])
        self.assertEqual(prepared["workers"][0]["service_area_id"], 1)
        self.assertEqual(prepared["tickets"][0]["allowed"], [0])

    def test_contradicting_worker_area_is_reported_with_its_sources(self):
        issue = {
            "code": MISMATCH,
            "subject": "worker",
            "subject_id": 10,
            "sources": {"brigade": 2, "worker": 1},
        }
        prepared = check_eligibility(
            self.snapshot(worker_service_areas={}, worker_area_issues={"10": issue}), EPOCH
        )
        reason = prepared["excluded_workers"][0]["reason"]
        self.assertEqual(reason["code"], MISMATCH)
        self.assertEqual(reason["observed"]["sources"], {"brigade": 2, "worker": 1})

    def test_worker_of_another_area_is_excluded_on_a_roster_replan(self):
        prepared = check_eligibility(self.snapshot(worker_service_areas={"10": 2}), EPOCH)
        self.assertEqual(prepared["excluded_workers"][0]["reason"]["code"], "service_area_mismatch")


class Plan2DatabaseTests(CommittedDatabaseTestCase):
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
        self.ids = self.receipt["id_map"]
        self.area_id = self.ids["service_areas"]["101"]
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
            tickets_api.optional_planning_settings: lambda: self.settings,
            tickets_api.optional_provider_factory: lambda: provider_factory,
            tickets_api.optional_planner_client: FeasiblePlanner,
            tickets_api.get_clock: lambda: lambda: self.now,
            tickets_api.get_planning_engine: lambda: self.engine,
        }
        app.dependency_overrides.update(overrides)
        self.addCleanup(lambda: [app.dependency_overrides.pop(k, None) for k in overrides])
        self.client = self.enterContext(TestClient(app))
        self.headers = {
            "Authorization": "Bearer " + create_access_token({"sub": str(self.ids["users"]["1"])})
        }

    # Fixture helpers -------------------------------------------------------

    def worker(self, source_id):
        return self.ids["workers"][str(source_id)]

    def brigade_of(self, source_worker_id):
        return next(
            m["brigade_id"]
            for m in self.data["brigade_members"]
            if m["worker_id"] == source_worker_id
        )

    def fixture_shift(self, source_worker_id):
        worker = next(w for w in self.data["workers"] if w["user_id"] == source_worker_id)
        return (worker["workshift_start"].isoformat(), worker["workshift_end"].isoformat())

    def office_of(self, source_worker_id):
        brigade = self.brigade_of(source_worker_id)
        return next(b["office_id"] for b in self.data["brigades"] if b["id"] == brigade)

    def tickets_for(self, *source_worker_ids):
        brigades = {self.brigade_of(w) for w in source_worker_ids}
        return [
            self.ids["tickets"][str(t["id"])]
            for t in self.data["tickets"]
            if t["brigade_id"] in brigades
        ]

    def day_url(self, suffix=""):
        return f"/api/v1/planning/areas/{self.area_id}/{ROUTE_DATE.isoformat()}{suffix}"

    def preview(self, ticket_ids, worker_ids, expected=201):
        response = self.client.post(
            "/api/v1/planning/preview",
            json={
                "route_date": ROUTE_DATE.isoformat(),
                "allow_partial": True,
                "ticket_ids": ticket_ids,
                "worker_ids": worker_ids,
            },
            headers=self.headers,
        )
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def apply(self, plan):
        response = self.client.post(
            f"/api/v1/planning/plans/{plan['plan_id']}/apply", headers=self.headers
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def replan(self, base_revision, expected=201):
        response = self.client.post(
            self.day_url("/replan/preview"),
            json={"base_day_revision": base_revision},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def current(self):
        response = self.client.get(self.day_url("/current"), headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def requested_workers(self, plan):
        with Session(self.engine) as session:
            stored = session.get(PlanningPlan, plan["plan_id"])
            return sorted(stored.input_snapshot["request"]["worker_ids"])

    def emergency(self, source_worker_id):
        response = self.client.post(
            "/api/v1/tickets",
            json={
                "location_id": self.ids["locations"]["1"],
                "service_area_id": self.area_id,
                "title": "Авария в течение дня",
                "work_type_id": self.ids["work_types"]["1"],
                "category": "emergency",
                "priority": 1,
                "received_at": self.now.isoformat(),
                "sla_deadline_at": "2030-01-15T18:00:00+03:00",
                "visit_window_start": "2030-01-15T11:00:00+03:00",
                "visit_window_end": "2030-01-15T17:00:00+03:00",
                "estimated_duration_minutes": 30,
            },
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 201, response.text)
        ticket = response.json()
        brigade = self.client.put(
            f"/api/v1/tickets/{ticket['id']}/brigade",
            json={"brigade_id": self.ids["brigades"][str(self.brigade_of(source_worker_id))]},
            headers=self.headers,
        )
        self.assertEqual(brigade.status_code, 200, brigade.text)
        with Session(self.engine) as session, session.begin():
            session.add(
                TicketAppliance(
                    ticket_id=ticket["id"],
                    appliance_id=self.ids["appliances"]["1"],
                    office_id=self.ids["offices"][str(self.office_of(source_worker_id))],
                    quantity=1,
                )
            )
        return ticket

    def other_area(self, code="plan2-other"):
        with Session(self.engine) as session, session.begin():
            area = ServiceArea(code=code, name="Соседний участок")
            session.add(area)
            session.flush()
            return area.id

    # Roster ----------------------------------------------------------------

    def test_first_apply_admits_every_selected_engineer_including_an_idle_one(self):
        w9, w10 = self.worker(9), self.worker(10)
        plan = self.preview(self.tickets_for(9), [w9, w10])
        self.assertEqual({route["worker_id"] for route in plan["routes"]}, {w9})
        self.apply(plan)

        current = self.current()
        self.assertEqual([entry["worker_id"] for entry in current["roster"]], [w9, w10])
        idle = next(entry for entry in current["roster"] if entry["worker_id"] == w10)
        self.assertEqual(idle["service_area_id"], self.area_id)
        self.assertEqual((idle["workshift_start"], idle["workshift_end"]), self.fixture_shift(10))
        self.assertNotIn(w10, {visit["worker_id"] for visit in current["visits"]})

    def test_emergency_replan_keeps_the_roster_and_never_takes_the_rest_of_the_area(self):
        w9 = self.worker(9)
        initial = self.apply(self.preview(self.tickets_for(9), [w9]))
        emergency = self.emergency(9)

        proposal = self.replan(initial["day_revision"])
        # Before plan 2 this was every engineer of the area (9, 10, 11 and 12).
        self.assertEqual(self.requested_workers(proposal), [w9])
        self.assertEqual({item["worker_id"] for item in proposal["excluded_workers"]}, set())
        self.assertIn(
            emergency["id"],
            [stop["ticket_id"] for route in proposal["routes"] for stop in route["stops"]],
        )
        applied = self.apply(proposal)

        current = self.current()
        self.assertEqual(current["revision"], applied["day_revision"])
        self.assertEqual([entry["worker_id"] for entry in current["roster"]], [w9])
        diff = self.client.get(self.day_url("/diff"), headers=self.headers).json()
        self.assertIsNone(diff["roster"])

        second = self.apply(self.replan(applied["day_revision"]))
        self.assertEqual(self.requested_workers({"plan_id": second["plan_id"]}), [w9])

    def test_idle_engineer_stays_in_the_roster_across_replans(self):
        w9, w10 = self.worker(9), self.worker(10)
        initial = self.apply(self.preview(self.tickets_for(9), [w9, w10]))
        first = self.apply(self.replan(initial["day_revision"]))
        second = self.apply(self.replan(first["day_revision"]))
        self.assertEqual(self.requested_workers({"plan_id": second["plan_id"]}), [w9, w10])
        self.assertEqual([entry["worker_id"] for entry in self.current()["roster"]], [w9, w10])

    def test_replan_keeps_the_shift_the_engineer_was_admitted_with(self):
        w9 = self.worker(9)
        initial = self.apply(self.preview(self.tickets_for(9), [w9]))
        with Session(self.engine) as session, session.begin():
            session.execute(
                update(Worker)
                .where(Worker.user_id == w9)
                .values(workshift_start=time(12), workshift_end=time(14))
            )
        proposal = self.replan(initial["day_revision"])
        with Session(self.engine) as session:
            stored = session.get(PlanningPlan, proposal["plan_id"])
            row = next(w for w in stored.input_snapshot["workers"] if w["user_id"] == w9)
        self.assertEqual((row["workshift_start"], row["workshift_end"]), self.fixture_shift(9))

    def test_manual_assignment_admits_an_engineer_explicitly_and_records_it(self):
        w9, w10 = self.worker(9), self.worker(10)
        initial = self.apply(self.preview(self.tickets_for(9), [w9]))
        ticket_id = self.tickets_for(10)[0]

        assigned = self.client.put(
            f"/api/v1/tickets/{ticket_id}/assignees",
            json={"worker_id": w10, "is_pinned": False},
            headers=self.headers,
        )
        self.assertEqual(assigned.status_code, 200, assigned.text)
        current = self.current()
        self.assertEqual(current["reason"], "manual_edit")
        self.assertEqual([entry["worker_id"] for entry in current["roster"]], [w9, w10])
        self.assertEqual(current["diff"]["roster"], {"added": [w10], "removed": []})
        admitted = next(entry for entry in current["roster"] if entry["worker_id"] == w10)
        self.assertEqual(admitted["source"], "manual_assignment")

        proposal = self.replan(current["revision"])
        self.assertEqual(self.requested_workers(proposal), [w9, w10])
        self.assertGreater(current["revision"], initial["day_revision"])

    def test_legacy_revision_rebuilds_its_roster_only_from_its_planning_snapshot(self):
        w9, w10 = self.worker(9), self.worker(10)
        initial = self.apply(self.preview(self.tickets_for(9), [w9, w10]))
        with Session(self.engine) as session, session.begin():
            session.execute(update(DayPlanRevision).values(roster=None))

        proposal = self.replan(initial["day_revision"])
        self.assertEqual(self.requested_workers(proposal), [w9, w10])
        self.apply(proposal)
        rebuilt = self.current()["roster"]
        self.assertEqual([entry["worker_id"] for entry in rebuilt], [w9, w10])
        self.assertEqual({entry["source"] for entry in rebuilt}, {"reconstructed_from_snapshot"})

    def test_legacy_revision_without_any_record_refuses_instead_of_taking_the_area(self):
        initial = self.apply(self.preview(self.tickets_for(9), [self.worker(9)]))
        with Session(self.engine) as session, session.begin():
            session.execute(
                text(
                    "UPDATE day_plan_revisions "
                    "SET roster = NULL, plan_id = NULL, plan_state = '{}'::jsonb"
                )
            )
        refused = self.replan(initial["day_revision"], expected=409)
        self.assertEqual(refused["detail"]["code"], "day_roster_unrecoverable")

    def test_rostered_engineer_whose_area_became_inconsistent_is_excluded_with_a_reason(self):
        w9, w10 = self.worker(9), self.worker(10)
        initial = self.apply(self.preview(self.tickets_for(9), [w9, w10]))
        other = self.other_area()
        with Session(self.engine) as session, session.begin():
            session.execute(
                update(Worker).where(Worker.user_id == w10).values(service_area_id=other)
            )

        proposal = self.replan(initial["day_revision"])
        excluded = {item["worker_id"]: item["reason"] for item in proposal["excluded_workers"]}
        self.assertEqual(excluded[w10]["code"], MISMATCH)
        # The brigade, its office and the stock office still say the plan's area.
        self.assertEqual(
            excluded[w10]["observed"]["sources"],
            {
                "brigade": self.area_id,
                "brigade_office": self.area_id,
                "stock_office": self.area_id,
                "worker": other,
            },
        )

    # Territory ---------------------------------------------------------------

    def test_engineer_without_any_area_is_refused_not_given_the_request_area(self):
        w12 = self.worker(12)
        with Session(self.engine) as session, session.begin():
            session.execute(
                update(Worker)
                .where(Worker.user_id == w12)
                .values(service_area_id=None, stock_office_id=None)
            )
            session.query(BrigadeMember).filter(BrigadeMember.worker_id == w12).delete()

        refused = self.preview(self.tickets_for(9), [self.worker(9), w12], expected=422)
        self.assertEqual(refused["detail"]["code"], MISSING)
        self.assertEqual(refused["detail"]["subject"], "worker")
        self.assertEqual(refused["detail"]["workers"][0]["subject_id"], w12)

        ticket_id = self.tickets_for(12)[0]
        manual = self.client.put(
            f"/api/v1/tickets/{ticket_id}/assignees",
            json={"worker_id": w12, "is_pinned": False},
            headers=self.headers,
        )
        self.assertEqual(manual.status_code, 422, manual.text)
        self.assertEqual(manual.json()["detail"]["code"], MISSING)

    def test_contradicting_profile_and_brigade_block_every_path_with_the_same_code(self):
        w10 = self.worker(10)
        other = self.other_area()
        with Session(self.engine) as session, session.begin():
            session.execute(
                update(Worker).where(Worker.user_id == w10).values(service_area_id=other)
            )
        ticket_id = self.tickets_for(10)[0]

        planned = self.preview([ticket_id], [w10], expected=422)
        self.assertEqual(planned["detail"]["code"], MISMATCH)

        preview = self.client.post(
            f"/api/v1/tickets/{ticket_id}/assign/preview",
            json={"worker_id": w10},
            headers=self.headers,
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertFalse(preview.json()["is_eligible"])
        self.assertEqual(preview.json()["violations"][0]["code"], MISMATCH)

        manual = self.client.put(
            f"/api/v1/tickets/{ticket_id}/assignees",
            json={"worker_id": w10, "is_pinned": False},
            headers=self.headers,
        )
        self.assertEqual(manual.status_code, 422, manual.text)
        self.assertEqual(manual.json()["detail"]["code"], MISMATCH)

        route = self.client.post(
            "/api/v1/routes",
            json={
                "worker_id": w10,
                "route_date": ROUTE_DATE.isoformat(),
                "stops": [
                    {
                        "location_id": self.ids["locations"]["1"],
                        "ticket_id": ticket_id,
                        "arrival_at": "2030-01-15T09:00:00+03:00",
                    }
                ],
            },
            headers=self.headers,
        )
        self.assertEqual(route.status_code, 422, route.text)
        self.assertEqual(route.json()["detail"]["code"], MISMATCH)

    def test_direct_route_save_cannot_send_an_engineer_to_another_area(self):
        other = self.other_area()
        ticket_id = self.tickets_for(9)[0]
        with Session(self.engine) as session, session.begin():
            session.execute(
                text("UPDATE tickets SET service_area_id = :a WHERE id = :t"),
                {
                    "a": other,
                    "t": ticket_id,
                },
            )
            location_id = session.scalar(
                text("SELECT location_id FROM tickets WHERE id = :t"), {"t": ticket_id}
            )
        route = self.client.post(
            "/api/v1/routes",
            json={
                "worker_id": self.worker(9),
                "route_date": ROUTE_DATE.isoformat(),
                "stops": [
                    {
                        "location_id": location_id,
                        "ticket_id": ticket_id,
                        "arrival_at": "2030-01-15T09:00:00+03:00",
                    }
                ],
            },
            headers=self.headers,
        )
        self.assertEqual(route.status_code, 422, route.text)
        detail = route.json()["detail"]
        self.assertEqual(detail["code"], "service_area_mismatch")
        self.assertEqual(detail["ticket_service_area_id"], other)

    def test_brigade_cannot_take_in_an_engineer_of_another_area(self):
        other = self.other_area()
        w12 = self.worker(12)
        with Session(self.engine) as session, session.begin():
            session.execute(
                update(Worker).where(Worker.user_id == w12).values(service_area_id=other)
            )
            session.query(BrigadeMember).filter(BrigadeMember.worker_id == w12).delete()
        brigade_id = self.ids["brigades"][str(self.brigade_of(9))]
        brigade = self.client.get(f"/api/v1/brigades/{brigade_id}", headers=self.headers).json()

        moved = self.client.put(
            f"/api/v1/brigades/{brigade_id}/members",
            json={
                "foreman_id": brigade["foreman_id"],
                "office_id": brigade["office_id"],
                "worker_ids": [*brigade["worker_ids"], w12],
            },
            headers=self.headers,
        )
        self.assertEqual(moved.status_code, 422, moved.text)
        self.assertEqual(moved.json()["detail"]["code"], MISMATCH)
        self.assertEqual(moved.json()["detail"]["workers"][0]["subject_id"], w12)
        with Session(self.engine) as session:
            self.assertIsNone(
                session.scalar(select(BrigadeMember).where(BrigadeMember.worker_id == w12))
            )

    def test_cities_of_one_area_share_a_plan_while_another_area_stays_out(self):
        w9 = self.worker(9)
        tickets = self.tickets_for(9)
        with Session(self.engine) as session, session.begin():
            city = City(name="Домодедово")
            session.add(city)
            session.flush()
            street = Street(city_id=city.id, name="Каширское шоссе")
            session.add(street)
            session.flush()
            # Another city, the same area: the building belongs to the area of the plan.
            far = Building(
                city_id=city.id,
                street_id=street.id,
                service_area_id=self.area_id,
                number="1-Д",
            )
            session.add(far)
            session.flush()
            far_location = Location(building_id=far.id, latitude=55.44, longitude=37.76)
            session.add(far_location)
            session.flush()
            session.execute(
                text("UPDATE tickets SET location_id = :l WHERE id = :t"),
                {"l": far_location.id, "t": tickets[0]},
            )

        plan = self.preview(tickets, [w9])
        visited = {stop["ticket_id"] for route in plan["routes"] for stop in route["stops"]}
        self.assertIn(tickets[0], visited)
        self.assertEqual(plan["unassigned"], [])

        other = self.other_area("plan2-same-city-other")
        with Session(self.engine) as session, session.begin():
            session.execute(
                text("UPDATE tickets SET service_area_id = :a WHERE id = :t"),
                {"a": other, "t": tickets[1]},
            )
        mixed = self.preview(tickets, [w9], expected=422)
        self.assertEqual(mixed["detail"]["code"], "multiple_service_areas")

    def test_consistency_report_lists_every_blocking_link_without_changing_it(self):
        clean = self.client.get("/api/v1/service-areas/consistency", headers=self.headers)
        self.assertEqual(clean.status_code, 200, clean.text)
        self.assertEqual(
            clean.json(), {"consistent": True, "workers": [], "brigades": [], "tickets": []}
        )

        w10 = self.worker(10)
        other = self.other_area()
        office_id = self.ids["offices"][str(self.office_of(9))]
        with Session(self.engine) as session, session.begin():
            session.execute(
                update(Worker).where(Worker.user_id == w10).values(service_area_id=other)
            )
            session.execute(
                text("UPDATE offices SET service_area_id = :a WHERE id = :o"),
                {"a": other, "o": office_id},
            )
        report = self.client.get("/api/v1/service-areas/consistency", headers=self.headers).json()
        self.assertFalse(report["consistent"])
        by_worker = {issue["subject_id"]: issue for issue in report["workers"]}
        self.assertEqual(by_worker[w10]["code"], MISMATCH)
        # One office serves the whole area, so every brigade and stock of it moved.
        self.assertEqual(
            by_worker[w10]["sources"],
            {
                "brigade": self.area_id,
                "brigade_office": other,
                "stock_office": other,
                "worker": other,
            },
        )
        self.assertEqual(by_worker[self.worker(9)]["sources"]["brigade_office"], other)
        source_office = self.office_of(9)
        self.assertEqual(
            sorted(issue["subject_id"] for issue in report["brigades"]),
            sorted(
                self.ids["brigades"][str(b["id"])]
                for b in self.data["brigades"]
                if b["office_id"] == source_office
            ),
        )
        with Session(self.engine) as session:
            self.assertEqual(session.get(Worker, w10).service_area_id, other)

        worker_token = {
            "Authorization": "Bearer " + create_access_token({"sub": str(self.ids["users"]["9"])})
        }
        denied = self.client.get("/api/v1/service-areas/consistency", headers=worker_token)
        self.assertEqual(denied.status_code, 403, denied.text)


if __name__ == "__main__":
    unittest.main()

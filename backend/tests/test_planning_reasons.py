"""Structured reasons and bounded diagnostics on small hand-checked problems, without a DB."""

import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.modules.planning import diagnostics, reasons
from app.modules.planning.eligibility import prepare
from app.modules.planning.policy import ExecutionPolicy
from app.modules.planning.solver_contract import SolveRequest

MOSCOW = ZoneInfo("Europe/Moscow")
EPOCH = datetime(2030, 1, 15, tzinfo=MOSCOW)
SHIFT = (480, 1080)


def problem(service, allowed, windows=None, walk_gaps=(), gaps=()):
    """Depots 0 (drive) and 1 (walk); tasks from node 2; 10 min by car, 30 on foot."""
    size = 2 + len(service)
    times = {"drive": 10, "walk": 30}
    matrices = {}
    for profile, minutes in times.items():
        closed = set(gaps) | (set(walk_gaps) if profile == "walk" else set())
        rows = [
            [0 if i == j else None if (i, j) in closed else minutes for j in range(size)]
            for i in range(size)
        ]
        matrices[profile] = {"time_minutes": rows, "distance_meters": rows}
    windows = windows or {}
    return SolveRequest(
        num_vehicles=2,
        starts=[0, 1],
        ends=[0, 1],
        vehicle_profiles=["drive", "walk"],
        vehicle_time_windows=[SHIFT, SHIFT],
        matrices=matrices,
        time_windows=[SHIFT, SHIFT] + [windows.get(n, SHIFT) for n in range(2, size)],
        service_times=[0, 0, *service],
        allowed_vehicles={str(n): v for n, v in allowed.items()},
        penalties=[0, 0] + [1] * len(service),
        ticket_policies=[
            {
                "ticket_id": 101 + node,
                "category": "repair",
                "priority": 3,
                "received_at": 0,
                "sla_deadline_at": None,
            }
            for node in range(2, size)
        ],
        time_capacity=1440,
        slack_max=1440,
    )


def worker(user_id, profile, office_id):
    return {
        "user_id": user_id,
        "profile": profile,
        "office_id": office_id,
        "location_id": office_id,
        "window": list(SHIFT),
        "skill_ids": {1},
    }


PREPARED = {
    "workers": [worker(21, "drive", 1), worker(22, "walk", 2)],
    "epoch": EPOCH,
    "policy": ExecutionPolicy(),
}


def nodes(count):
    tickets = [
        {
            "kind": "ticket",
            "location_id": 100 + n,
            "ticket": {
                "id": 100 + n,
                "location_id": 100 + n,
                "visit_window_end": "2030-01-15T18:00:00+03:00",
                "rejected": [],
            },
        }
        for n in range(2, 2 + count)
    ]
    return [{"kind": "depot", "location_id": 1}, {"kind": "depot", "location_id": 2}, *tickets]


def solution(dropped, route=()):
    steps = [SimpleNamespace(node=n) for n in (0, *route, 0)]
    return SimpleNamespace(
        routes=[SimpleNamespace(vehicle_id=0, steps=steps)], dropped_nodes=list(dropped)
    )


class DroppedVisitDiagnosticsTests(unittest.TestCase):
    def diagnose(self, data, dropped, route=()):
        result = diagnostics.diagnose_dropped(
            PREPARED, data, nodes(len(data.service_times) - 2), solution(dropped, route)
        )
        return {item["ticket_id"]: item for item in result}

    def test_single_visit_failures_distinguish_transport_address_window_and_shift(self):
        data = problem(
            service=[30, 30, 30, 600],
            allowed={2: [1], 3: [0, 1], 4: [0, 1], 5: [0]},
            windows={4: (480, 485)},
            walk_gaps=[(1, 2)],
            gaps=[(0, 3), (1, 3)],
        )
        result = self.diagnose(data, [2, 3, 4, 5])

        transport = result[102]["reason"]
        self.assertEqual(
            (transport["code"], transport["category"]), ("unreachable_by_transport", "transport")
        )
        detail = result[102]["candidates"][0]["reason"]
        self.assertEqual(detail["observed"], {"routing_mode": "walk"})
        self.assertEqual(detail["required"], {"routing_modes": ["drive"]})

        address = result[103]["reason"]
        self.assertEqual(
            (address["code"], address["category"]), ("address_unreachable", "unreachable")
        )
        self.assertEqual(address["ids"], {"worker_ids": [21, 22]})

        late = result[104]["reason"]
        self.assertEqual(late["code"], "arrival_after_window")
        self.assertIn("у всех: не успевает к окну", late["message"])
        car = result[104]["candidates"][0]["reason"]
        self.assertIn("прибудет в 08:10", car["message"])
        self.assertEqual(car["observed"], {"earliest_arrival": "2030-01-15T08:10:00+03:00"})

        shift = result[105]["reason"]
        self.assertEqual(shift["code"], "return_after_shift_end")
        self.assertEqual(
            result[105]["candidates"][0]["reason"]["observed"],
            {"earliest_route_end": "2030-01-15T18:20:00+03:00"},
        )

    def test_full_route_is_not_impossible_and_free_slot_is_a_search_miss(self):
        data = problem(service=[540, 60, 20], allowed={2: [0], 3: [0], 4: [0]})
        result = self.diagnose(data, [3, 4], route=[2])

        full = result[103]
        self.assertEqual(full["reason"]["code"], "no_slot_in_computed_plan")
        self.assertEqual(full["reason"]["category"], "capacity")
        self.assertIn("не доказательство невозможности", full["reason"]["message"])
        self.assertEqual(full["candidates"][0]["reason"]["code"], "route_full")

        missed = result[104]
        self.assertEqual(missed["reason"]["code"], "feasible_slot_missed")
        self.assertEqual(
            missed["reason"]["observed"],
            {"search_time_limit_seconds": 5, "category": "repair", "priority": 3},
        )
        slot = missed["candidates"][0]["reason"]
        self.assertEqual(slot["code"], "slot_available")
        self.assertEqual(slot["observed"], {"position": 0})
        self.assertIn("первым визитом", slot["message"])

    def test_slot_after_a_planned_visit_names_that_visit(self):
        data = problem(
            service=[60, 60], allowed={2: [0], 3: [0]}, windows={2: (480, 500), 3: (700, 1000)}
        )
        slot = self.diagnose(data, [3], route=[2])[103]["candidates"][0]["reason"]
        self.assertEqual(slot["ids"], {"ticket_ids": [102]})
        self.assertEqual(slot["observed"], {"position": 1})
        self.assertIn("после заявки №102", slot["message"])

    def test_rejected_candidates_from_precheck_are_kept_next_to_route_checks(self):
        data = problem(service=[540, 60], allowed={2: [0], 3: [0]})
        graph = nodes(2)
        graph[3]["ticket"]["rejected"] = [
            {"worker_id": 22, "reason": reasons.missing_skill([7], {7})}
        ]
        result = diagnostics.diagnose_dropped(PREPARED, data, graph, solution([3], route=[2]))
        self.assertEqual(
            [(c["worker_id"], c["reason"]["code"]) for c in result[0]["candidates"]],
            [(21, "route_full"), (22, "missing_skill")],
        )


class ResourceEstimateTests(unittest.TestCase):
    def setUp(self):
        self.data = problem(service=[540, 60, 60], allowed={2: [0], 3: [0], 4: [0]})
        self.graph = nodes(3)
        self.dropped = diagnostics.diagnose_dropped(
            PREPARED, self.data, self.graph, solution([3, 4], route=[2])
        )

    def test_copies_of_real_engineers_are_an_explicit_estimate(self):
        estimate = diagnostics.estimate_resources(PREPARED, self.data, self.graph, self.dropped)
        self.assertEqual(
            {k: estimate[k] for k in ("is_estimate", "complete", "additional_workers")},
            {"is_estimate": True, "complete": True, "additional_workers": 1},
        )
        self.assertEqual(estimate["covered_ticket_ids"], [103, 104])
        self.assertEqual(
            estimate["workers"],
            [{"like_worker_id": 21, "ticket_ids": [103, 104], "travel_minutes": 30}],
        )
        self.assertIn("не доказанный минимальный штат", estimate["message"])

    def test_check_budget_stops_the_estimate_and_says_so(self):
        with patch.object(diagnostics, "ESTIMATE_CHECK_BUDGET", 1):
            estimate = diagnostics.estimate_resources(PREPARED, self.data, self.graph, self.dropped)
        self.assertFalse(estimate["complete"])
        self.assertEqual(estimate["covered_ticket_ids"], [103])
        self.assertEqual(estimate["uncovered_ticket_ids"], [104])
        self.assertIn("оценка неполная", estimate["message"])

    def test_nothing_to_estimate_without_capacity_rejections(self):
        self.assertIsNone(diagnostics.estimate_resources(PREPARED, self.data, self.graph, []))


def snapshot(workers, *, allocations=None, reserved=1, stock=3):
    location = {"latitude": 55.75, "longitude": 37.61}
    return {
        "policy_version": 1,
        "request": {
            "route_date": "2030-01-15",
            "ticket_ids": [101],
            "worker_ids": [w["user_id"] for w in workers],
            "allow_partial": True,
        },
        "tickets": [
            {
                "id": 101,
                "status": "planned",
                "work_type": "Монтаж",
                "work_type_id": 1,
                "location_id": 10,
                "visit_window_start": "2030-01-15T10:00:00+03:00",
                "visit_window_end": "2030-01-15T12:00:00+03:00",
                "estimated_duration_minutes": 120,
            }
        ],
        "workers": [
            {k: w[k] for k in ("user_id", "workshift_start", "workshift_end")}
            | {"transport_type": "car", "is_on_line": w.get("on_line", True)}
            for w in workers
        ],
        "roles": [{"id": w["user_id"], "role": "worker"} for w in workers],
        "locations": [{"id": i, **location} for i in (1, 2, 10)],
        "offices": [{"id": 1, "location_id": 1}, {"id": 2, "location_id": 2}],
        "brigades": [{"id": 1, "office_id": 1}, {"id": 2, "office_id": 2}],
        "members": [{"worker_id": w["user_id"], "brigade_id": w["office"]} for w in workers],
        "busy_tickets": [],
        "assignments": [],
        "skills": [
            {"worker_id": w["user_id"], "skill_id": s} for w in workers for s in w["skills"]
        ],
        "work_types": [{"id": 1, "name": "Монтаж", "work_minutes": 60, "documents_minutes": 10}],
        "rules": [{"work_type_id": 1, "service_duration_source": "ticket_estimate"}],
        "required_skills": [{"work_type_id": 1, "skill_id": 7}],
        "required_appliances": [{"work_type_id": 1, "appliance_id": 5, "quantity": 1}],
        "allocations": [{"ticket_id": 101, "appliance_id": 5, "office_id": 1, "quantity": 1}]
        if allocations is None
        else allocations,
        "appliances": [{"id": 5, "name": "Роутер", "is_active": True}],
        "stocks": [{"office_id": 1, "appliance_id": 5, "stock": stock}],
        "reservations": [{"office_id": 1, "appliance_id": 5, "quantity": reserved}],
    }


def engineer(user_id, office=1, skills=(7,), start="09:00:00", end="18:00:00", on_line=True):
    return {
        "user_id": user_id,
        "office": office,
        "skills": skills,
        "workshift_start": start,
        "workshift_end": end,
        "on_line": on_line,
    }


NOW = datetime(2030, 1, 14, 12, tzinfo=MOSCOW)


class PrecheckReasonTests(unittest.TestCase):
    def test_each_engineer_gets_the_first_failed_rule(self):
        team = [
            engineer(21, skills=()),
            engineer(22, office=2),
            engineer(23, start="19:00:00", end="23:00:00"),
            engineer(24, end="11:30:00"),
        ]
        prepared = prepare(snapshot(team), NOW)
        self.assertEqual(prepared["tickets"], [])
        item = prepared["unassigned"][0]
        self.assertEqual(
            [
                (c["worker_id"], c["reason"]["code"], c["reason"]["category"])
                for c in item["candidates"]
            ],
            [
                (21, "missing_skill", "skill"),
                (22, "office_mismatch", "area"),
                (23, "window_outside_shift", "time"),
                (24, "service_after_shift_end", "time"),
            ],
        )
        self.assertEqual(
            (item["reason"]["code"], item["reason"]["category"]), ("no_eligible_worker", "mixed")
        )
        self.assertEqual(item["reason"]["ids"], {"worker_ids": [21, 22, 23, 24]})
        self.assertIn("Не подходит ни один из 4 инженеров", item["reason"]["message"])
        by_worker = {c["worker_id"]: c["reason"] for c in item["candidates"]}
        self.assertEqual(by_worker[21]["ids"], {"skill_ids": [7]})
        self.assertEqual(by_worker[22]["observed"], {"office_id": 2})
        self.assertEqual(by_worker[22]["required"], {"office_ids": [1]})
        self.assertEqual(
            by_worker[24]["message"],
            "Работа 120 мин при самом раннем начале 10:00 закончится в 12:00,"
            " после конца смены 11:30",
        )

    def test_skill_that_nobody_has_is_named_directly(self):
        prepared = prepare(snapshot([engineer(21, skills=()), engineer(22, skills=(3,))]), NOW)
        reason = prepared["unassigned"][0]["reason"]
        self.assertEqual(reason["code"], "missing_skill")
        self.assertEqual(reason["ids"], {"skill_ids": [7]})
        self.assertEqual(reason["message"], "Ни у одного из выбранных инженеров (2) нет навыка №7")

    def test_eligible_ticket_keeps_rejections_of_other_engineers(self):
        prepared = prepare(snapshot([engineer(21), engineer(22, office=2)]), NOW)
        ticket = prepared["tickets"][0]
        self.assertEqual(ticket["allowed"], [0])
        self.assertEqual([c["worker_id"] for c in ticket["rejected"]], [22])
        self.assertEqual(ticket["required_skill_ids"], [7])

    def test_inventory_reasons_carry_observed_and_required_quantities(self):
        missing = prepare(snapshot([engineer(21)], allocations=[]), NOW)["unassigned"][0]["reason"]
        self.assertEqual(missing["code"], "equipment_not_reserved")
        self.assertEqual(missing["message"], "Не зарезервировано оборудование: «Роутер» 0 из 1")
        self.assertEqual(
            missing["observed"],
            {
                "appliances": [{"appliance_id": 5, "quantity": 0}],
                "category": "repair",
                "priority": 3,
            },
        )
        self.assertEqual(
            missing["required"],
            {
                "appliances": [{"appliance_id": 5, "quantity": 1}],
                "planning_priority_order": ["emergency", "connection", "repair", "additional"],
                "ticket_priority": 3,
            },
        )
        broken = prepare(snapshot([engineer(21)], reserved=5), NOW)["unassigned"][0]["reason"]
        self.assertEqual(broken["code"], "stock_inconsistent")
        self.assertIn("«Роутер» в офисе №1: резерв 5, остаток 3", broken["message"])

    def test_no_available_engineers_is_not_reported_as_a_ticket_defect(self):
        prepared = prepare(snapshot([engineer(21, on_line=False)]), NOW)
        self.assertEqual(prepared["excluded_workers"][0]["reason"]["code"], "worker_offline")
        reason = prepared["unassigned"][0]["reason"]
        self.assertEqual(
            (reason["code"], reason["category"]), ("no_available_workers", "availability")
        )

    def test_started_shift_states_both_moments(self):
        late = datetime(2030, 1, 15, 9, 30, tzinfo=MOSCOW)
        reason = prepare(snapshot([engineer(21)]), late)["excluded_workers"][0]["reason"]
        self.assertEqual(reason["code"], "shift_already_started")
        self.assertEqual(reason["observed"], {"calculated_at": "2030-01-15T09:30:00+03:00"})
        self.assertEqual(reason["required"], {"calculated_before": "2030-01-15T09:00:00+03:00"})

    def test_sla_deadline_is_checked_separately_from_the_visit_window(self):
        data = snapshot([engineer(21)])
        data["tickets"][0].update(
            work_type_id=1,
            received_at="2030-01-15T10:00:00+03:00",
            sla_deadline_at="2030-01-15T11:00:00+03:00",
        )

        prepared = prepare(data, NOW)

        self.assertEqual(prepared["tickets"], [])
        self.assertEqual(prepared["unassigned"][0]["reason"]["code"], "sla_deadline_missed")


class TextHelpersTests(unittest.TestCase):
    def test_russian_plural_forms(self):
        self.assertEqual(
            [reasons.engineers(n) for n in (1, 2, 5, 11, 21, 22, 112)],
            [
                "1 инженер",
                "2 инженера",
                "5 инженеров",
                "11 инженеров",
                "21 инженер",
                "22 инженера",
                "112 инженеров",
            ],
        )
        self.assertEqual(
            [reasons.genitive(n, "инженера", "инженеров") for n in (1, 4, 11, 21)],
            ["1 инженера", "4 инженеров", "11 инженеров", "21 инженера"],
        )

    def test_legacy_codes_become_structured_reasons(self):
        public = {
            "routes": [],
            "unassigned": [{"ticket_id": 1, "reason": "not_selected_by_solver"}],
            "excluded_workers": [{"worker_id": 2, "reason": "worker_busy"}],
        }
        upgraded = reasons.legacy_public(public)
        self.assertEqual(upgraded["outcome"], "empty")
        self.assertEqual(upgraded["unassigned"][0]["reason"]["category"], "search")
        self.assertEqual(upgraded["excluded_workers"][0]["reason"]["category"], "availability")
        self.assertEqual(public["unassigned"][0]["reason"], "not_selected_by_solver")

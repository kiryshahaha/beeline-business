"""T11/A21/A22: organizer files become tickets with provenance, a baseline and a report."""

from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.db.session import get_session
from app.main import app
from app.modules.source_import import router as source_router
from app.modules.source_import.geocoding import GeoapifyGeocoder
from app.modules.source_import.profile import MOSCOW
from tests.source_fixtures import OFFICE, VISITS, control_csv, demand_csv, geocode_response
from tests.support import DatabaseTestCase

IMPORT = "/api/v1/data/sources/import"
CSV = "text/csv"


class SourceImportApiTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()

        def override_session():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session

        self.calls = []

        def recording(request):
            self.calls.append(request.url.params["text"])
            return geocode_response(request)

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[source_router.get_geocoder] = lambda: GeoapifyGeocoder(
            "fixture-key", transport=httpx.MockTransport(recording)
        )
        self.addCleanup(app.dependency_overrides.pop, get_session)
        self.addCleanup(app.dependency_overrides.pop, source_router.get_geocoder)
        self.client = self.enterContext(TestClient(app))
        self.users = {role: self.user(role) for role in ("observer", "foreman", "worker")}
        self.observer = self.auth("observer")

    def user(self, role):
        return self.connection.execute(
            text("""
                INSERT INTO users (name, surname, username, password_hash, role)
                VALUES ('Тест', 'Импорт', :username, 'hash', :role) RETURNING id
            """),
            {"username": f"{role}_{uuid4().hex[:8]}", "role": role},
        ).scalar_one()

    def auth(self, role):
        return {"Authorization": f"Bearer {create_access_token({'sub': str(self.users[role])})}"}

    def upload(self, content, name="Центр Синтетические данные.csv", **params):
        return self.client.post(
            IMPORT, params=params, files={"file": (name, content, CSV)}, headers=self.observer
        )

    def scalar(self, sql, **params):
        return self.connection.execute(text(sql), params).scalar()

    def test_dry_run_reports_everything_and_writes_nothing(self):
        response = self.upload(demand_csv())
        self.assertEqual(response.status_code, 200, response.text)
        report = response.json()
        self.assertTrue(report["dry_run"])
        self.assertIsNone(report["import_id"])
        self.assertEqual(report["kind"], "demand")
        self.assertEqual(report["dataset"], "Центр")
        self.assertEqual(report["service_area"]["code"], "source-tsentr")
        self.assertEqual(
            report["counts"], {"read": 6, "created": 6, "updated": 0, "unchanged": 0, "rejected": 0}
        )
        self.assertEqual(
            report["by_category"], {"additional": 1, "connection": 2, "emergency": 1, "repair": 2}
        )
        self.assertEqual(report["file"]["encoding"], "cp1251")
        self.assertEqual(report["office"]["address"], OFFICE)
        self.assertEqual(report["pending_geocoding"], 6)
        self.assertEqual(report["work_date"], "2026-09-10")
        for table in ("tickets", "source_imports", "source_records", "source_addresses", "offices"):
            self.assertEqual(self.scalar(f"SELECT count(*) FROM {table}"), 0, table)
        self.assertEqual(self.calls, [])

    def test_demand_import_creates_tickets_with_provenance(self):
        report = self.upload(demand_csv(), dry_run=False).json()
        self.assertIsInstance(report["import_id"], int)
        area = report["service_area"]["id"]
        rows = (
            self.connection.execute(
                text("""
                SELECT r.external_id, r.row_number, r.bk_type, r.hd_type, r.raw, r.outcome,
                       t.title, t.category, t.priority, t.estimated_duration_minutes,
                       t.visit_window_start, t.visit_window_end, t.received_at,
                       t.service_area_id, t.lifecycle_state, c.name AS city, s.name AS street,
                       b.number, b.block, d.name AS district
                FROM source_records r
                JOIN tickets t ON t.id = r.ticket_id
                JOIN locations l ON l.id = t.location_id
                JOIN buildings b ON b.id = l.building_id
                JOIN streets s ON s.id = b.street_id
                JOIN cities c ON c.id = b.city_id
                JOIN districts d ON d.id = b.district_id
                WHERE r.kind = 'demand' ORDER BY r.row_number
            """)
            )
            .mappings()
            .all()
        )
        self.assertEqual([r["external_id"] for r in rows], [v[0] for v in VISITS])
        first, emergency = rows[0], rows[2]
        self.assertEqual((first["row_number"], first["outcome"]), (2, "created"))
        self.assertEqual(first["raw"]["Тип заявки HD"], "Конвергенция абонента")
        self.assertEqual(first["title"], "Подключение: Конвергенция абонента")
        self.assertEqual((first["category"], first["priority"]), ("connection", 2))
        self.assertEqual(first["estimated_duration_minutes"], 70)
        self.assertEqual(first["visit_window_start"], datetime(2026, 9, 10, 10, tzinfo=MOSCOW))
        self.assertEqual(first["received_at"], first["visit_window_start"])
        self.assertEqual(first["service_area_id"], area)
        self.assertEqual(first["lifecycle_state"], "waiting_assignment")
        self.assertEqual(
            (first["city"], first["street"], first["number"], first["block"], first["district"]),
            ("Москва", "ул. Вымышленная", "1", "корп. 2", "Центральный"),
        )
        self.assertEqual(
            (emergency["category"], emergency["estimated_duration_minutes"]), ("emergency", 80)
        )
        self.assertEqual(emergency["city"], "Учебногорск")
        self.assertEqual(
            emergency["visit_window_end"], datetime(2026, 9, 10, 23, 59, tzinfo=MOSCOW)
        )
        self.assertEqual(self.scalar("SELECT count(DISTINCT location_id) FROM tickets"), 5)
        office = self.connection.execute(
            text(
                "SELECT o.name, s.name FROM offices o JOIN locations l ON l.id = o.location_id "
                "JOIN buildings b ON b.id = l.building_id JOIN streets s ON s.id = b.street_id"
            )
        ).one()
        self.assertEqual(tuple(office), ("Офис участка Центр", "ул. Учебная"))
        self.assertIn("не настроены требования планирования", report["warnings"][-1]["message"])
        saved = self.client.get(
            f"/api/v1/data/sources/imports/{report['import_id']}", headers=self.observer
        )
        self.assertEqual(saved.json(), report)
        listed = self.client.get("/api/v1/data/sources/imports", headers=self.observer).json()
        self.assertEqual(listed[0]["dataset"], "Центр")
        self.assertEqual(listed[0]["counts"]["created"], 6)

    def test_every_row_is_imported_or_rejected_with_its_place(self):
        bad = [
            (
                "201",
                "Неизвестная работа",
                "X",
                "10.09.2026 10:00",
                "10.09.2026 12:00",
                "Р",
                "Москва, ул.А, д. 1",
            ),
            (
                "202",
                "Дозаказ",
                "X",
                "10.09.2026 25:00",
                "10.09.2026 12:00",
                "Р",
                "Москва, ул.А, д. 1",
            ),
            (
                "203",
                "Дозаказ",
                "X",
                "10.09.2026 12:00",
                "10.09.2026 11:00",
                "Р",
                "Москва, ул.А, д. 1",
            ),
            ("204", "Дозаказ", "X", "10.09.2026 10:00", "10.09.2026 12:00", "Р", "где-то"),
            ("", "Дозаказ", "X", "10.09.2026 10:00", "10.09.2026 12:00", "Р", "Москва, ул.А, д. 1"),
        ]
        extra = [[v[0], v[1], v[2], v[3], v[4], v[5], v[6], "", "Нет"] for v in bad]
        visits = [*VISITS, VISITS[0]]  # an identical repeated row
        repeated = list(VISITS[1])
        repeated[3], repeated[4] = "10.09.2026 20:00", "10.09.2026 22:00"
        visits.append(tuple(repeated))  # same ticket number, another visit
        content = demand_csv(visits, extra=extra)
        report = self.upload(content, dry_run=False).json()
        self.assertEqual(report["counts"]["read"], 13)
        self.assertEqual(report["counts"]["created"], 7)
        self.assertEqual(report["counts"]["rejected"], 6)
        codes = {(r["row"], r["code"]) for r in report["rejected"]}
        self.assertEqual(
            codes,
            {
                (8, "duplicate_row"),
                (10, "unknown_source_type"),
                (11, "invalid_time"),
                (12, "invalid_window"),
                (13, "address_unparsed"),
                (14, "missing_external_id"),
            },
        )
        [unknown] = [r for r in report["rejected"] if r["code"] == "unknown_source_type"]
        self.assertEqual((unknown["column"], unknown["external_id"]), ("Тип заявки BK", "201"))
        self.assertIn("версия соответствий 1", unknown["message"])
        self.assertEqual(
            self.scalar("SELECT count(*) FROM source_records WHERE external_id = '102#2'"), 1
        )
        self.assertTrue(any("102#2" in w["message"] for w in report["warnings"]))
        self.assertEqual(
            self.scalar("SELECT outcome FROM source_records WHERE external_id = '201'"), "rejected"
        )
        self.assertEqual(self.scalar("SELECT count(*) FROM tickets"), 7)

    def test_reimport_is_idempotent_updates_changes_and_protects_work_in_progress(self):
        self.upload(demand_csv(), dry_run=False)
        again = self.upload(demand_csv(), dry_run=False).json()
        self.assertEqual(again["counts"]["unchanged"], 6)
        self.assertEqual(self.scalar("SELECT count(*) FROM tickets"), 6)
        changed = [list(v) for v in VISITS[:4]]
        changed[0][4] = "10.09.2026 13:00"
        changed[1][4] = "10.09.2026 15:00"
        ticket_102 = self.scalar("SELECT ticket_id FROM source_records WHERE external_id = '102'")
        worker = self.user("worker")
        self.connection.execute(
            text(
                "INSERT INTO workers (user_id, workshift_start, workshift_end) "
                "VALUES (:w, '09:00', '18:00')"
            ),
            {"w": worker},
        )
        self.connection.execute(
            text(
                "UPDATE tickets SET assigned_worker_id = :w, lifecycle_state = 'assigned' "
                "WHERE id = :t"
            ),
            {"w": worker, "t": ticket_102},
        )
        report = self.upload(demand_csv([tuple(v) for v in changed]), dry_run=False).json()
        self.assertEqual(
            report["counts"], {"read": 4, "created": 0, "updated": 1, "unchanged": 2, "rejected": 1}
        )
        self.assertEqual(report["rejected"][0]["code"], "ticket_in_work")
        end, revision = self.connection.execute(
            text(
                "SELECT t.visit_window_end, t.revision FROM tickets t JOIN source_records r "
                "ON r.ticket_id = t.id WHERE r.external_id = '101'"
            )
        ).one()
        self.assertEqual((end, revision), (datetime(2026, 9, 10, 13, tzinfo=MOSCOW), 2))
        absent = [w for w in report["warnings"] if "external_ids" in w][0]
        self.assertEqual(absent["external_ids"], ["105", "106"])
        self.assertEqual(self.scalar("SELECT count(*) FROM tickets"), 6)

    def test_control_is_a_baseline_with_brigades_as_workers_and_a_replay(self):
        refused = self.upload(control_csv(), name="Центр Контрольное распределение.csv")
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertEqual(refused.json()["detail"]["code"], "demand_import_required")
        self.upload(demand_csv(), dry_run=False)
        report = self.upload(
            control_csv(),
            name="Центр Контрольное распределение.csv",
            dry_run=False,
            workshift_start="08:00:00",
            workshift_end="20:00:00",
            transport_type="walking",
        ).json()
        self.assertEqual(report["kind"], "control")
        self.assertEqual(report["counts"]["created"], 6)
        baseline = report["baseline"]
        self.assertEqual((baseline["workers"], baseline["workers_created"]), (3, 3))
        self.assertEqual((baseline["assigned_rows"], baseline["rows_without_brigade"]), (5, 1))
        self.assertEqual(
            report["replay"]["statuses"],
            {
                "cancelled": 1,
                "completed": 1,
                "en_route": 1,
                "in_progress": 1,
                "not_dispatched": 1,
                "overdue": 1,
            },
        )
        workers = (
            self.connection.execute(
                text("""
                SELECT u.name, u.surname, u.role, w.workshift_start, w.workshift_end,
                       w.transport_type, w.service_area_id, w.stock_office_id,
                       array_agg(s.skill ORDER BY s.skill) AS skills
                FROM workers w JOIN users u ON u.id = w.user_id
                JOIN worker_skill_assignments a ON a.worker_id = w.user_id
                JOIN worker_skills s ON s.id = a.skill_id
                GROUP BY 1, 2, 3, 4, 5, 6, 7, 8 ORDER BY u.surname
            """)
            )
            .mappings()
            .all()
        )
        by_surname = {w["surname"]: w for w in workers}
        self.assertEqual(set(by_surname), {"Тестов", "Пробный"})
        self.assertEqual(len(workers), 3)
        tester = by_surname["Тестов"]
        self.assertEqual((tester["name"], tester["role"]), ("Бригада", "worker"))
        self.assertEqual(tester["skills"], ["Локальные работы", "Работы на подключение и дозаказы"])
        self.assertEqual(str(tester["workshift_start"]), "08:00:00")
        self.assertEqual(tester["transport_type"], "walking")
        self.assertEqual(tester["service_area_id"], report["service_area"]["id"])
        self.assertIsNotNone(tester["stock_office_id"])
        # The organizer's split is a baseline, not our plan: every ticket stays unassigned.
        self.assertEqual(
            self.scalar("SELECT count(*) FROM tickets WHERE assigned_worker_id IS NOT NULL"), 0
        )
        replay = self.client.get(
            f"/api/v1/data/sources/areas/{report['service_area']['id']}/replay",
            headers=self.observer,
        ).json()
        events = {e["external_id"]: e for e in replay["events"]}
        self.assertEqual(events["3000101"]["status"], "completed")
        self.assertEqual(events["3000101"]["at"], "2026-09-10T12:00:00+03:00")
        self.assertEqual(events["3000103"]["at"], None)
        self.assertEqual(events["3000103"]["time_basis"], "export_snapshot")
        self.assertIsNone(events["3000105"]["worker_id"])
        again = self.upload(
            control_csv(), name="Центр Контрольное распределение.csv", dry_run=False
        ).json()
        self.assertEqual(
            (again["counts"]["unchanged"], again["baseline"]["workers_created"]), (6, 0)
        )

    def test_same_surname_in_two_areas_stays_two_people(self):
        for dataset in ("Север", "Юг"):
            self.upload(demand_csv(), dataset=dataset, dry_run=False)
            self.upload(control_csv(), dataset=dataset, dry_run=False)
        rows = self.connection.execute(
            text(
                "SELECT w.service_area_id, count(*) FROM users u "
                "JOIN workers w ON w.user_id = u.id "
                "WHERE u.surname = 'Тестов' GROUP BY 1"
            )
        ).all()
        self.assertEqual(len(rows), 2)

    def test_control_row_without_demand_counterpart_and_unknown_status_are_reported(self):
        self.upload(demand_csv(VISITS[:3]), dry_run=False)
        other = list(VISITS[3])
        report = self.upload(
            control_csv(
                [VISITS[0], tuple(other)],
                extra=[
                    [
                        "3000999",
                        "Дозаказ",
                        "Потеряна",
                        "X",
                        "10.09.2026 10:00",
                        "10.09.2026 12:00",
                        "Р",
                        "Москва, ул.А, д. 1",
                        "Бригада Тестов",
                        "",
                        "Нет",
                    ],
                ],
            ),
            kind="control",
            dataset="Центр",
            dry_run=False,
        ).json()
        codes = {r["external_id"]: r["code"] for r in report["rejected"]}
        self.assertEqual(
            codes, {"3000104": "no_matching_demand_row", "3000999": "unknown_source_status"}
        )

    def test_geocoding_statuses_manual_review_and_cache(self):
        visits = [
            *VISITS[:2],
            (
                "107",
                "Дозаказ",
                "X",
                "10.09.2026 10:00",
                "10.09.2026 12:00",
                "Р",
                "Москва, ул.Нигдеевка, д. 1",
                None,
                "",
                "Отправлена",
            ),
            VISITS[4],
        ]
        report = self.upload(demand_csv(visits), dry_run=False, geocode=True).json()
        self.assertEqual(report["coordinates"], {"ambiguous": 1, "geocoded": 2, "unresolved": 1})
        # A later import without geocoding keeps the stored statuses and the candidate.
        again = self.upload(demand_csv(visits), dry_run=False).json()
        self.assertEqual(again["coordinates"], report["coordinates"])
        self.assertEqual(report["office"]["coordinates"], "geocoded")
        self.assertEqual(len(self.calls), 5)
        addresses = self.client.get("/api/v1/data/sources/addresses", headers=self.observer).json()
        by_status = {}
        for address in addresses:
            by_status.setdefault(address["status"], []).append(address)
        [weak] = by_status["ambiguous"]
        self.assertIsNone(weak["latitude"])
        self.assertIsNotNone(weak["candidate_latitude"])
        [missing] = by_status["unresolved"]
        self.assertTrue(all(a["latitude"] is not None for a in by_status["geocoded"]))
        reviewed = self.client.put(
            f"/api/v1/data/sources/addresses/{weak['id']}",
            json={"latitude": 55.7, "longitude": 37.6},
            headers=self.observer,
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        self.assertEqual(reviewed.json()["status"], "manual")
        self.assertEqual(float(reviewed.json()["latitude"]), 55.7)
        self.calls.clear()
        self.upload(demand_csv(visits), dry_run=False, geocode=True)
        self.assertEqual(self.calls, [missing["raw_address"]])
        filtered = self.client.get(
            "/api/v1/data/sources/addresses", params={"status": "manual"}, headers=self.observer
        ).json()
        self.assertEqual([a["id"] for a in filtered], [weak["id"]])

    def test_geocoding_without_key_errors_roles_and_formats(self):
        app.dependency_overrides[source_router.get_geocoder] = lambda: None
        response = self.upload(demand_csv(), dry_run=False, geocode=True)
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(
            self.upload(demand_csv(), name="x.json").json()["detail"]["code"], "source_format"
        )
        self.assertEqual(self.upload(demand_csv(office=None)).status_code, 422)
        self.assertEqual(
            self.upload(control_csv(), kind="demand").json()["detail"]["code"],
            "office_address_missing",
        )
        with patch("app.modules.source_import.profile.MAX_FILE_BYTES", 100):
            self.assertEqual(self.upload(demand_csv()).status_code, 422)
        for role in ("foreman", "worker"):
            response = self.client.post(
                IMPORT, files={"file": ("x.csv", demand_csv(), CSV)}, headers=self.auth(role)
            )
            self.assertEqual(response.status_code, 403)
        self.assertEqual(
            self.client.post(IMPORT, files={"file": ("x.csv", b"x", CSV)}).status_code, 401
        )
        self.assertEqual(
            self.client.get("/api/v1/data/sources/mapping", headers=self.observer).json()[
                "mapping_version"
            ],
            1,
        )
        self.assertEqual(
            self.client.put(
                "/api/v1/data/sources/addresses/2147483647",
                json={"latitude": 1, "longitude": 1},
                headers=self.observer,
            ).status_code,
            404,
        )

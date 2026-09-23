"""Real PostgreSQL import/export, authorization, route snapshots and concurrent numbering."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.db.session import get_session
from app.main import app
from app.modules.data_exchange.formats import parse_file, serialize
from app.modules.data_exchange.registry import TABLES
from app.modules.data_exchange.service import import_data
from app.modules.routing.schemas import RouteCreate
from app.modules.routing.service import save_routes
from generate_synthetic import generate_dataset
from tests.support import DatabaseTestCase


class ExchangeAndRoutesApiTests(DatabaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dataset = generate_dataset(seed=701, tickets=32, workers=8, days=2)
        normalized = parse_file(serialize(cls.dataset, "csv"), "data.zip")
        with Session(cls.engine) as session:
            cls.receipt = import_data(session, normalized)
        cls.ids = cls.receipt["id_map"]

    def setUp(self):
        super().setUp()

        def override_session():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        self.addCleanup(app.dependency_overrides.pop, get_session)
        self.client = self.enterContext(TestClient(app))
        self.observer = self.auth(1)
        self.worker = self.auth(9)
        self.other_worker = self.auth(10)
        self.foreman = self.auth(3)

    def auth(self, source_id):
        return {
            "Authorization": "Bearer "
            + create_access_token({"sub": str(self.ids["users"][str(source_id)])})
        }

    def route(self, **overrides):
        return {
            "worker_id": self.ids["workers"]["9"],
            "route_date": "2026-09-23",
            "stops": [
                {
                    "location_id": self.ids["locations"]["1"],
                    "ticket_id": self.ids["tickets"]["1"],
                    "arrival_at": "2026-09-23T09:00:00+03:00",
                    "service_start_at": "2026-09-23T09:00:00+03:00",
                    "service_end_at": "2026-09-23T09:30:00+03:00",
                    "waiting_minutes": 0,
                    "duration_source": "ticket_estimate",
                },
                {
                    "location_id": self.ids["locations"]["2"],
                    "arrival_at": "2026-09-23T10:00:00+03:00",
                    "service_start_at": "2026-09-23T10:00:00+03:00",
                    "service_end_at": "2026-09-23T10:30:00+03:00",
                    "waiting_minutes": 0,
                    "duration_source": "ticket_estimate",
                },
            ],
            **overrides,
        }

    def upload(self, data, *, format="csv", dry_run=False, headers=None):
        extension = "zip" if format == "csv" else "xlsx"
        return self.client.post(
            "/api/v1/data/import",
            params={"dry_run": str(dry_run).lower()},
            files={"file": ("data." + extension, serialize(data, format))},
            headers=headers or self.observer,
        )

    def test_import_is_atomic_idempotent_and_remaps_related_ids(self):
        data = generate_dataset(seed=702, tickets=24, workers=4, days=1)
        # Skill names are a unique domain key: use a separate catalog for a second dataset.
        for skill in data["worker_skills"]:
            skill["skill"] += " 702"
        before = self.session.scalar(select(func.count()).select_from(TABLES["tickets"]))
        result = self.upload(data, format="xlsx")
        self.assertEqual(result.status_code, 200, result.text)
        ids = result.json()["id_map"]
        self.assertNotEqual(ids["users"]["1"], 1)
        row = (
            self.session.execute(
                select(TABLES["tickets"]).where(TABLES["tickets"].c.id == ids["tickets"]["1"])
            )
            .mappings()
            .one()
        )
        self.assertEqual(row["location_id"], ids["locations"]["1"])
        again = self.upload(data)
        self.assertEqual(again.status_code, 200, again.text)
        self.assertTrue(again.json()["duplicate"])
        self.assertEqual(again.json()["id_map"], ids)
        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(TABLES["tickets"])), before + 24
        )
        route = (
            self.session.execute(
                select(TABLES["routes"]).where(TABLES["routes"].c.id == ids["routes"]["1"])
            )
            .mappings()
            .one()
        )
        self.assertEqual(route["geojson"]["properties"]["worker_id"], ids["workers"]["9"])
        self.assertEqual(
            route["geojson"]["features"][0]["properties"]["location_id"], ids["locations"]["1"]
        )

    def test_dry_run_has_no_rows_or_receipt_and_error_rolls_back(self):
        data = {"cities": [{"id": 1, "name": "Импорт только для проверки"}]}
        before = self.session.scalar(select(func.count()).select_from(TABLES["cities"]))
        response = self.upload(data, dry_run=True)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["dry_run"])
        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(TABLES["cities"])), before
        )
        data["districts"] = [{"id": 1, "name": "Неверная ссылка", "city_id": 999999}]
        response = self.upload(data)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(TABLES["cities"])), before
        )
        self.assertEqual(response.json()["detail"]["table"], "districts")

    def test_database_error_reports_original_row_after_blank_lines(self):
        response = self.client.post(
            "/api/v1/data/import?entity=cities&dry_run=false",
            files={"file": ("cities.csv", b"id,name\n1,Unique city\n\n2,Unique city\n")},
            headers=self.observer,
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["detail"]["row"], 4)
        self.assertEqual(
            self.session.scalar(
                select(func.count())
                .select_from(TABLES["cities"])
                .where(TABLES["cities"].c.name == "Unique city")
            ),
            0,
        )

    def test_unsupported_postgres_json_character_returns_422_and_rolls_back(self):
        event = dict(self.dataset["notification_events"][0])
        event["data"] = {"text": "invalid\x00character"}
        event["recipient_id"] = self.ids["users"][str(event["recipient_id"])]
        event["ticket_id"] = self.ids["tickets"][str(event["ticket_id"])]
        table = TABLES["notification_events"]
        before = self.session.scalar(select(func.count()).select_from(table))
        response = self.upload({"notification_events": [event]})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["detail"]["table"], "notification_events")
        self.assertEqual(self.session.scalar(select(func.count()).select_from(table)), before)

    def test_database_rejects_missing_or_null_geojson_collection_type(self):
        for geojson in ({}, {"type": None, "features": []}, {"type": "Point", "features": []}):
            with self.subTest(geojson=geojson), self.assertRaises(IntegrityError):
                with self.session.begin_nested():
                    self.session.execute(
                        TABLES["routes"]
                        .insert()
                        .values(
                            worker_id=self.ids["workers"]["9"],
                            route_date=date(2026, 10, 1),
                            route_number=1,
                            geojson=geojson,
                        )
                    )

    def test_authentication_and_authorization_for_exchange_and_routes(self):
        for path in ("/api/v1/data/schema", "/api/v1/data/export", "/api/v1/routes"):
            self.assertEqual(self.client.get(path).status_code, 401)
        for headers in (self.worker, self.foreman):
            self.assertEqual(
                self.client.get("/api/v1/data/export", headers=headers).status_code, 403
            )
            self.assertEqual(
                self.upload({"cities": [{"id": 1, "name": "Denied"}]}, headers=headers).status_code,
                403,
            )
            self.assertEqual(
                self.client.post("/api/v1/routes", json=self.route(), headers=headers).status_code,
                403,
            )

    def test_routes_number_by_worker_and_date_and_preserve_geojson(self):
        for number in (1, 2):
            response = self.client.post("/api/v1/routes", json=self.route(), headers=self.observer)
            self.assertEqual(response.status_code, 201, response.text)
            route = response.json()
            self.assertEqual(route["route_number"], number)
            self.assertNotEqual(route["id"], number)
            points = route["geojson"]["features"][:2]
            self.assertEqual([p["properties"]["sequence"] for p in points], [1, 2])
            self.assertEqual(points[0]["properties"]["arrival_at"], "2026-09-23T09:00:00+03:00")
            self.assertEqual(
                points[0]["properties"]["service_start_at"], "2026-09-23T09:00:00+03:00"
            )
            self.assertEqual(
                points[0]["properties"]["service_end_at"], "2026-09-23T09:30:00+03:00"
            )
            self.assertEqual(points[0]["properties"]["waiting_minutes"], 0)
            self.assertEqual(
                points[0]["geometry"]["coordinates"],
                [
                    self.dataset["locations"][0]["longitude"],
                    self.dataset["locations"][0]["latitude"],
                ],
            )
        response = self.client.post(
            "/api/v1/routes",
            json=self.route(worker_id=self.ids["workers"]["10"]),
            headers=self.observer,
        )
        self.assertEqual(response.json()["route_number"], 1)
        downloaded = self.client.get(f"/api/v1/routes/{route['id']}/geojson", headers=self.worker)
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.json(), route["geojson"])
        self.assertIn("application/geo+json", downloaded.headers["content-type"])
        self.assertEqual(
            self.client.get(f"/api/v1/routes/{route['id']}", headers=self.other_worker).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(f"/api/v1/routes/{route['id']}", headers=self.foreman).status_code, 200
        )
        listed = self.client.get("/api/v1/routes?route_date=2026-09-23", headers=self.worker).json()
        self.assertEqual([r["route_number"] for r in listed], [1, 2])

    def test_invalid_routes_and_atomic_batch(self):
        bad_payloads = []
        for mutate in (
            lambda p: p.update(worker_id=2147483647),
            lambda p: p.update(stops=[]),
            lambda p: p.update(route_date="2026-09-22"),
            lambda p: p["stops"][0].update(arrival_at="2026-09-23T09:00:00"),
            lambda p: p["stops"][1].update(
                arrival_at="2026-09-23T08:00:00+03:00",
                service_start_at="2026-09-23T08:00:00+03:00"
            ),
            lambda p: p["stops"][0].update(location_id=2147483647),
            lambda p: p["stops"][0].update(location_id=self.ids["locations"]["17"]),
            lambda p: p["stops"][0].update(ticket_id=self.ids["tickets"]["2"]),
            lambda p: p.update(geometry={"type": "LineString", "coordinates": [[0, 0], [1, 1]]}),
            lambda p: p.update(geometry={"type": "LineString", "coordinates": [[181, 0], [1, 1]]}),
        ):
            payload = self.route()
            mutate(payload)
            bad_payloads.append(payload)
        before = self.session.scalar(select(func.count()).select_from(TABLES["routes"]))
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                response = self.client.post("/api/v1/routes", json=payload, headers=self.observer)
                self.assertEqual(response.status_code, 422, response.text)
        response = self.client.post(
            "/api/v1/routes/batch",
            json={"routes": [self.route(), bad_payloads[0]]},
            headers=self.observer,
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(TABLES["routes"])), before
        )

    def test_single_point_and_night_route(self):
        payload = self.route(
            route_date="2026-09-23",
            stops=[
                {
                    "location_id": self.ids["locations"]["1"],
                    "arrival_at": "2026-09-23T23:30:00+03:00",
                    "service_start_at": "2026-09-23T23:30:00+03:00",
                    "service_end_at": "2026-09-24T00:00:00+03:00",
                    "waiting_minutes": 0,
                    "duration_source": "ticket_estimate",
                },
                {
                    "location_id": self.ids["locations"]["2"],
                    "arrival_at": "2026-09-24T01:30:00+03:00",
                    "service_start_at": "2026-09-24T01:30:00+03:00",
                    "service_end_at": "2026-09-24T02:00:00+03:00",
                    "waiting_minutes": 0,
                    "duration_source": "ticket_estimate",
                },
            ],
        )
        response = self.client.post("/api/v1/routes", json=payload, headers=self.observer)
        self.assertEqual(response.status_code, 201, response.text)
        payload["stops"] = payload["stops"][:1]
        response = self.client.post("/api/v1/routes", json=payload, headers=self.observer)
        self.assertEqual(len(response.json()["geojson"]["features"]), 1)

    def test_worker_transport_patch_preserves_other_profile_fields(self):
        user_id = self.ids["workers"]["9"]
        for transport in ("car", "walking", "bicycle", "public_transport"):
            response = self.client.patch(
                f"/api/v1/users/{user_id}",
                json={"worker_profile": {"transport_type": transport}},
                headers=self.observer,
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["worker_profile"]["transport_type"], transport)
        response = self.client.patch(
            f"/api/v1/users/{user_id}",
            json={"worker_profile": {"workshift_end": "07:00:00"}},
            headers=self.observer,
        )
        self.assertEqual(response.json()["worker_profile"]["transport_type"], "public_transport")
        for value in (None, "helicopter", ""):
            self.assertEqual(
                self.client.patch(
                    f"/api/v1/users/{user_id}",
                    json={"worker_profile": {"transport_type": value}},
                    headers=self.observer,
                ).status_code,
                422,
            )
        self.assertEqual(
            self.client.patch(
                f"/api/v1/users/{user_id}",
                json={"worker_profile": {"transport_type": "car"}},
                headers=self.worker,
            ).status_code,
            403,
        )

    def test_concurrent_numbering_on_real_transactions(self):
        payload = RouteCreate.model_validate(
            self.route(
                route_date="2026-09-25",
                stops=[
                    {
                        "location_id": self.ids["locations"]["1"],
                        "arrival_at": "2026-09-25T09:00:00+03:00",
                        "service_start_at": "2026-09-25T09:00:00+03:00",
                        "service_end_at": "2026-09-25T09:30:00+03:00",
                        "waiting_minutes": 0,
                        "duration_source": "ticket_estimate",
                    },
                ],
            )
        )

        def save(_):
            with Session(self.engine) as session:
                return save_routes(session, [payload])[0].route_number

        with ThreadPoolExecutor(max_workers=6) as pool:
            numbers = list(pool.map(save, range(12)))
        self.assertEqual(sorted(numbers), list(range(1, 13)))

    def test_roles_and_stock_rules_cannot_be_bypassed_by_import(self):
        data = {
            "workers": [
                {
                    "user_id": self.ids["users"]["1"],
                    "workshift_start": "09:00:00",
                    "workshift_end": "18:00:00",
                    "transport_type": "walking",
                }
            ]
        }
        response = self.upload(data)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIsNone(
            self.session.scalar(
                select(TABLES["workers"].c.user_id).where(
                    TABLES["workers"].c.user_id == self.ids["users"]["1"]
                )
            )
        )
        # Ticket 1 is planned; source appliance 26 has zero stock.
        data = {
            "ticket_appliances": [
                {
                    "ticket_id": self.ids["tickets"]["1"],
                    "appliance_id": self.ids["appliances"]["26"],
                    "office_id": self.ids["offices"]["1"],
                    "quantity": 1,
                    "created_at": "2026-09-21T08:00:00+03:00",
                }
            ]
        }
        self.assertEqual(self.upload(data).status_code, 422)

    def test_schema_enumerates_all_tables_without_credentials(self):
        result = self.client.get("/api/v1/data/schema", headers=self.observer)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(set(result.json()["tables"]), set(TABLES))
        self.assertNotIn("password_hash", [c["name"] for c in result.json()["tables"]["users"]])

    def test_concurrent_import_creates_one_receipt_and_one_copy(self):
        data = {"cities": [{"id": 1, "name": "Concurrent isolated import"}]}

        def upload(_):
            with Session(self.engine) as session:
                return import_data(session, data)

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(upload, range(4)))
        self.assertEqual(sum(not result["duplicate"] for result in results), 1)
        self.assertTrue(all(result["id_map"] == results[0]["id_map"] for result in results))

    def test_worker_creation_accepts_transport_and_defaults_for_old_clients(self):
        for index, transport in enumerate((None, "car", "bicycle", "public_transport")):
            profile = {
                "workshift_start": "09:00:00",
                "workshift_end": "18:00:00",
                "skills": ["Монтаж"],
            }
            if transport is not None:
                profile["transport_type"] = transport
            response = self.client.post(
                "/api/v1/users",
                headers=self.observer,
                json={
                    "name": "Тест",
                    "surname": "Транспорт",
                    "username": f"transport_create_{index}",
                    "password": "SyntheticOnly123!",
                    "role": "worker",
                    "worker_profile": profile,
                },
            )
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(
                response.json()["worker_profile"]["transport_type"], transport or "walking"
            )

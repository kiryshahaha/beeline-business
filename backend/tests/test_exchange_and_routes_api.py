"""Real PostgreSQL import/export, authorization, route snapshots and concurrent numbering."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
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
from app.modules.data_exchange.service import REFERENCE_KEYS, import_data
from app.modules.routing.schemas import RouteCreate
from app.modules.routing.service import save_routes
from generate_synthetic import generate_dataset
from tests.exchange_samples import add_journal_samples
from tests.support import DatabaseTestCase


class ExchangeAndRoutesApiTests(DatabaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dataset = add_journal_samples(
            generate_dataset(seed=701, tickets=32, workers=8, days=2), seed=701
        )
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
                },
                {
                    "location_id": self.ids["locations"]["2"],
                    "arrival_at": "2026-09-23T10:00:00+03:00",
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
        # A second package of the same city: its streets, houses, skills, equipment and
        # office are the ones already loaded, its people and requests are new.
        data = add_journal_samples(
            generate_dataset(seed=702, tickets=24, workers=4, days=1), seed=702
        )
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

    def test_another_package_reuses_reference_ids_without_creating_rows(self):
        names = (*REFERENCE_KEYS, "divisions", "service_areas")
        data = {name: deepcopy(self.dataset[name]) for name in names}
        before = {
            name: self.session.scalar(select(func.count()).select_from(TABLES[name]))
            for name in names
        }
        result = self.upload(data)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertFalse(result.json()["duplicate"])
        for name in REFERENCE_KEYS:
            with self.subTest(table=name):
                self.assertEqual(result.json()["id_map"][name], self.ids[name])
                self.assertEqual(
                    self.session.scalar(select(func.count()).select_from(TABLES[name])),
                    before[name],
                )

    def test_office_stock_is_added_once_and_dry_run_does_not_add_it(self):
        source = deepcopy(self.dataset["appliance_stocks"][0])
        source["office_id"] = self.ids["offices"][str(source["office_id"])]
        source["appliance_id"] = self.ids["appliances"][str(source["appliance_id"])]
        source["stock"] = 7
        table = TABLES["appliance_stocks"]
        query = select(table.c.stock).where(
            table.c.office_id == source["office_id"],
            table.c.appliance_id == source["appliance_id"],
        )
        before = self.session.scalar(query)
        data = {"appliance_stocks": [source]}
        dry_run = self.upload(data, dry_run=True)
        self.assertEqual(dry_run.status_code, 200, dry_run.text)
        self.assertEqual(self.session.scalar(query), before)
        applied = self.upload(data)
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertEqual(self.session.scalar(query), before + 7)
        repeated = self.upload(data, format="xlsx")
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertTrue(repeated.json()["duplicate"])
        self.assertEqual(self.session.scalar(query), before + 7)

    def test_existing_building_cannot_be_imported_into_another_service_area(self):
        source = deepcopy(self.dataset["buildings"][0])
        for field, table_name in (("city_id", "cities"), ("street_id", "streets")):
            source[field] = self.ids[table_name][str(source[field])]
        original_area = self.ids["service_areas"][str(source["service_area_id"])]
        source["service_area_id"] = next(
            value for value in self.ids["service_areas"].values() if value != original_area
        )
        result = self.upload({"buildings": [source]})
        self.assertEqual(result.status_code, 422, result.text)
        self.assertEqual(result.json()["detail"]["table"], "buildings")
        self.assertIn("service_area_id", str(result.json()["detail"]))
        table = TABLES["buildings"]
        self.assertEqual(
            self.session.scalar(
                select(table.c.service_area_id).where(
                    table.c.id == self.ids["buildings"][str(source["id"])]
                )
            ),
            original_area,
        )

    def test_duplicate_reference_in_one_package_is_rejected_for_new_and_existing_rows(self):
        table = TABLES["cities"]
        before = self.session.scalar(select(func.count()).select_from(table))
        for name in (self.dataset["cities"][0]["name"], "New import test city"):
            with self.subTest(name=name):
                result = self.upload(
                    {"cities": [{"id": 90001, "name": name}, {"id": 90002, "name": name}]}
                )
                self.assertEqual(result.status_code, 422, result.text)
                self.assertEqual(result.json()["detail"]["table"], "cities")
                self.assertEqual(result.json()["detail"]["row"], 3)
                self.assertEqual(
                    self.session.scalar(select(func.count()).select_from(table)), before
                )

    def test_duplicate_existing_work_type_in_one_package_is_rejected(self):
        first = deepcopy(self.dataset["work_types"][0])
        second = {**first, "id": 90002}
        result = self.upload({"work_types": [first, second]})
        self.assertEqual(result.status_code, 422, result.text)
        self.assertEqual(result.json()["detail"]["table"], "work_types")
        self.assertEqual(result.json()["detail"]["row"], 3)

    def test_import_preserves_existing_work_type_rules_skills_and_equipment(self):
        rule = deepcopy(self.dataset["work_type_planning_rules"][0])
        work_type_id = self.ids["work_types"][str(rule["work_type_id"])]
        names = (
            "work_type_planning_rules",
            "work_type_required_skills",
            "work_type_required_appliances",
        )

        def configuration():
            return {
                name: [
                    dict(row)
                    for row in self.session.execute(
                        select(TABLES[name]).where(TABLES[name].c.work_type_id == work_type_id)
                    ).mappings()
                ]
                for name in names
            }

        before = configuration()
        rule.update(
            work_type_id=work_type_id,
            configured_by=self.ids["users"]["2"],
            service_duration_source=(
                "ticket_estimate" if rule["service_duration_source"] == "work_norm" else "work_norm"
            ),
        )
        existing_skills = {row["skill_id"] for row in before["work_type_required_skills"]}
        new_skill = next(
            value for value in self.ids["worker_skills"].values() if value not in existing_skills
        )
        appliance = before["work_type_required_appliances"][0]
        new_appliance = next(
            value
            for value in self.ids["appliances"].values()
            if value not in {row["appliance_id"] for row in before["work_type_required_appliances"]}
        )
        data = {
            names[0]: [rule],
            names[1]: [{"work_type_id": work_type_id, "skill_id": new_skill}],
            names[2]: [
                {**appliance, "quantity": appliance["quantity"] + 5},
                {"work_type_id": work_type_id, "appliance_id": new_appliance, "quantity": 3},
            ],
        }
        result = self.upload(data)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(configuration(), before)

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
        # Engineer 10 serves another area: a direct save cannot bypass the territory rule.
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["detail"]["code"], "service_area_mismatch")
        response = self.client.post(
            "/api/v1/routes",
            json=self.route(
                worker_id=self.ids["workers"]["10"],
                stops=[
                    {
                        "location_id": self.ids["locations"]["2"],
                        "arrival_at": "2026-09-23T10:00:00+03:00",
                    }
                ],
            ),
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
            lambda p: p["stops"][1].update(arrival_at="2026-09-23T08:00:00+03:00"),
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
                },
                {
                    "location_id": self.ids["locations"]["2"],
                    "arrival_at": "2026-09-24T01:30:00+03:00",
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
        # A planned request of the day asks for more tools than the office has.
        planned = next(t for t in self.dataset["tickets"] if t["status"] == "planned")
        office = next(
            o["id"]
            for o in self.dataset["offices"]
            if o["service_area_id"] == planned["service_area_id"]
        )
        tool = next(a["id"] for a in self.dataset["appliances"] if a["type"] == "TOOL")
        stock = next(
            row["stock"]
            for row in self.dataset["appliance_stocks"]
            if (row["office_id"], row["appliance_id"]) == (office, tool)
        )
        data = {
            "ticket_appliances": [
                {
                    "ticket_id": self.ids["tickets"][str(planned["id"])],
                    "appliance_id": self.ids["appliances"][str(tool)],
                    "office_id": self.ids["offices"][str(office)],
                    "quantity": stock + 1,
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

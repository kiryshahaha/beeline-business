"""Round trips across migrated databases, including historical schema upgrades."""

import copy
from pathlib import Path

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.db.session import get_session
from app.main import app
from app.modules.data_exchange.formats import ExchangeError, parse_file, serialize
from app.modules.data_exchange.registry import TABLES
from app.modules.data_exchange.service import export_data, import_data
from app.modules.routing.schemas import RouteCreate
from app.modules.routing.service import save_routes
from generate_synthetic import generate_dataset
from testing.database import migrated_schema
from tests.support import DatabaseTestCase


class ExchangeRoundtripTests(DatabaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        data = generate_dataset(seed=800, tickets=80, workers=12, days=2)
        data["workers"][0]["is_on_line"] = False
        data["notification_events"][0]["data"]["actor_id"] = 1
        data["notification_events"][0]["websocket_delivered_at"] = None
        data["notification_events"][0]["push_delivered_at"] = None
        with Session(cls.engine) as session:
            cls.ids = import_data(session, parse_file(serialize(data, "csv"), "data.zip"))["id_map"]
            save_routes(
                session,
                [
                    RouteCreate.model_validate(
                        {
                            "worker_id": cls.ids["workers"]["9"],
                            "route_date": "2026-09-21",
                            "stops": [
                                {
                                    "location_id": cls.ids["locations"]["1"],
                                    "ticket_id": cls.ids["tickets"]["1"],
                                    "arrival_at": "2026-09-21T09:00:00+03:00",
                                }
                            ],
                        }
                    )
                ],
            )

    def test_complete_export_import_between_independent_schemas(self):
        with Session(self.engine) as session:
            source = export_data(session)
        for format, extension in (("csv", "zip"), ("xlsx", "xlsx")):
            with self.subTest(format=format), migrated_schema(self.admin_engine) as (engine, _):
                with engine.begin() as connection:
                    for name, table in TABLES.items():
                        if "id" in table.c:
                            connection.execute(
                                text(
                                    "SELECT setval(pg_get_serial_sequence(:table, 'id'), "
                                    "1000, true)"
                                ),
                                {"table": name},
                            )
                with Session(engine) as session:
                    receipt = import_data(
                        session, parse_file(serialize(source, format), "all." + extension)
                    )
                    destination = export_data(session)
                self.assertEqual(
                    {k: len(v) for k, v in source.items()},
                    {k: len(v) for k, v in destination.items()},
                )
                self.assertNotIn("password_hash", destination["users"][0])
                self.assertGreater(destination["users"][0]["id"], 1000)
                self.assertEqual(
                    [r["title"] for r in source["tickets"]],
                    [r["title"] for r in destination["tickets"]],
                )
                self.assertEqual(
                    [r["visit_window_start"] for r in source["tickets"]],
                    [r["visit_window_start"] for r in destination["tickets"]],
                )
                self.assertEqual(
                    [r["transport_type"] for r in source["workers"]],
                    [r["transport_type"] for r in destination["workers"]],
                )
                self.assertEqual(
                    [r["is_on_line"] for r in source["workers"]],
                    [r["is_on_line"] for r in destination["workers"]],
                )
                # IDs inside the equipment journal and the composite state key follow the rows.
                [held] = destination["worker_appliances"]
                [operation] = destination["appliance_operations"]
                [state] = destination["ticket_appliance_states"]
                self.assertEqual(operation["request"]["worker_id"], held["worker_id"])
                self.assertEqual(state["holder_worker_id"], held["worker_id"])
                self.assertIn(
                    (state["ticket_id"], state["appliance_id"]),
                    {(r["ticket_id"], r["appliance_id"]) for r in destination["ticket_appliances"]},
                )
                self.assertGreater(held["worker_id"], 1000)
                records = {r["kind"]: r for r in destination["source_records"]}
                self.assertEqual(records["brigade"]["worker_id"], held["worker_id"])
                self.assertIn(
                    records["demand"]["ticket_id"], {r["id"] for r in destination["tickets"]}
                )
                event = destination["notification_events"][0]
                self.assertEqual(
                    event["data"]["actor_id"],
                    receipt["id_map"]["users"][str(self.ids["users"]["1"])],
                )
                self.assertEqual(event["data"]["ticket_id"], event["ticket_id"])
                self.assertIsNotNone(event["push_delivered_at"])
                self.assertIsNotNone(event["websocket_delivered_at"])
                for route in destination["routes"]:
                    self.assertEqual(
                        route["worker_id"], route["geojson"]["properties"]["worker_id"]
                    )
                    for point in route["geojson"]["features"]:
                        if point["geometry"]["type"] == "Point":
                            self.assertGreater(point["properties"]["location_id"], 1000)
                            if point["properties"]["ticket_id"] is not None:
                                self.assertEqual(
                                    point["properties"]["ticket_id"],
                                    receipt["id_map"]["tickets"][str(self.ids["tickets"]["1"])],
                                )

    def test_legacy_district_keyed_package_imports_area_references(self):
        package_path = Path(__file__).resolve().parents[1] / "bruno/fixtures/dataset.zip"
        tables = parse_file(package_path.read_bytes(), package_path.name)
        referenced_tables = (
            "buildings",
            "divisions",
            "work_events",
            "worker_day_states",
            "day_plan_revisions",
        )

        with migrated_schema(self.admin_engine) as (engine, _):
            with engine.begin() as connection:
                connection.execute(
                    text("SELECT setval(pg_get_serial_sequence('service_areas', 'id'), 1000, true)")
                )
            with Session(engine) as session:
                receipt = import_data(session, tables)
                destination = export_data(session)

            for name in referenced_tables:
                imported_by_id = {row["id"]: row for row in destination[name]}
                for source in tables[name]:
                    district_id = receipt["id_map"]["districts"][str(source["_legacy_district_id"])]
                    service_area_id = next(
                        row["id"]
                        for row in destination["service_areas"]
                        if row["code"] == f"district_{district_id}"
                    )
                    imported_id = receipt["id_map"][name][str(source["id"])]
                    self.assertEqual(
                        imported_by_id[imported_id]["service_area_id"], service_area_id, name
                    )
                    self.assertNotEqual(service_area_id, district_id, name)

        invalid_tables = copy.deepcopy(tables)
        invalid_tables["buildings"][0]["_legacy_district_id"] = 2_147_483_647
        with migrated_schema(self.admin_engine) as (engine, _):
            with Session(engine) as session:
                initial_service_area_count = session.scalar(
                    text("SELECT count(*) FROM service_areas")
                )
            with Session(engine) as session:
                with self.assertRaisesRegex(ExchangeError, "Ссылка districts:"):
                    import_data(session, invalid_tables)
            with Session(engine) as session:
                self.assertEqual(session.scalar(text("SELECT count(*) FROM districts")), 0)
                self.assertEqual(
                    session.scalar(text("SELECT count(*) FROM service_areas")),
                    initial_service_area_count,
                )

    def test_export_http_returns_all_rows_and_safe_download_headers(self):
        def override_session():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        self.addCleanup(app.dependency_overrides.pop, get_session)
        headers = {
            "Authorization": "Bearer " + create_access_token({"sub": str(self.ids["users"]["1"])})
        }
        with TestClient(app) as client:
            for format, extension in (("csv", "zip"), ("xlsx", "xlsx")):
                response = client.get(
                    "/api/v1/data/export", params={"format": format}, headers=headers
                )
                self.assertEqual(response.status_code, 200, response.text[:100])
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertIn("attachment", response.headers["content-disposition"])
                parsed = parse_file(response.content, "data." + extension)
                self.assertEqual(len(parsed["tickets"]), 80)
                self.assertEqual(set(parsed), set(TABLES))
            self.assertEqual(
                client.get("/api/v1/data/export?format=pdf", headers=headers).status_code, 422
            )

    def test_upgrade_populated_0008_and_downgrade_keeps_old_worker_fields(self):
        with migrated_schema(self.admin_engine, "0008") as (engine, config):
            with engine.begin() as connection:
                user_id = connection.execute(
                    text(
                        "INSERT INTO users (name,surname,username,password_hash,role) "
                        "VALUES ('Test','Worker','migration_worker','hash','worker') RETURNING id"
                    )
                ).scalar_one()
                connection.execute(
                    text(
                        "INSERT INTO workers (user_id,workshift_start,workshift_end) "
                        "VALUES (:id,'22:00','06:00')"
                    ),
                    {"id": user_id},
                )
            with engine.connect() as connection:
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
                command.check(config)
                row = connection.execute(
                    text("SELECT user_id,workshift_start,workshift_end,transport_type FROM workers")
                ).one()
                self.assertEqual(row.transport_type, "walking")
                self.assertEqual(row.user_id, user_id)
                self.assertEqual(row.workshift_start.hour, 22)
                self.assertEqual(row.workshift_end.hour, 6)
                connection.commit()
                command.downgrade(config, "0008")
                self.assertNotIn(
                    "transport_type",
                    {c["name"] for c in inspect(connection).get_columns("workers")},
                )
                self.assertEqual(
                    connection.execute(text("SELECT user_id FROM workers")).scalar_one(), user_id
                )
                self.assertNotIn("routes", inspect(connection).get_table_names())

    def test_populated_day_revisions_upgrade_downgrade_and_upgrade_again(self):
        with migrated_schema(self.admin_engine, "0024") as (engine, config):
            with engine.begin() as connection:
                city_id = connection.execute(
                    text("INSERT INTO cities (name) VALUES ('T21 migration city') RETURNING id")
                ).scalar_one()
                district_id = connection.execute(
                    text(
                        "INSERT INTO districts (city_id,name) VALUES (:city,'T21 migration area') "
                        "RETURNING id"
                    ),
                    {"city": city_id},
                ).scalar_one()
                connection.execute(
                    text(
                        "INSERT INTO service_areas (code,name) VALUES (:code,'T21 migration area')"
                    ),
                    {"code": f"district_{district_id}"},
                )
                service_area_id = connection.execute(
                    text("SELECT id FROM service_areas WHERE code = :code"),
                    {"code": f"district_{district_id}"},
                ).scalar_one()
                actor_id = connection.execute(
                    text(
                        "INSERT INTO users (name,surname,username,password_hash,role) "
                        "VALUES ('T21','Migration','t21_migration','hash','observer') "
                        "RETURNING id"
                    )
                ).scalar_one()
                first_id = connection.execute(
                    text(
                        "INSERT INTO day_plan_revisions "
                        "(district_id,route_date,revision,actor_id,"
                        "fingerprint,result,is_current,created_at) "
                        "VALUES (:district,'2030-01-15',7,:actor,:fingerprint,:result,false,"
                        "'2030-01-15T08:00:00+00:00') RETURNING id"
                    ),
                    {
                        "district": district_id,
                        "actor": actor_id,
                        "fingerprint": "a" * 64,
                        "result": '{"legacy": 1}',
                    },
                ).scalar_one()
                second_id = connection.execute(
                    text(
                        "INSERT INTO day_plan_revisions "
                        "(district_id,route_date,revision,previous_revision,"
                        "actor_id,fingerprint,result,is_current,created_at) "
                        "VALUES (:district,'2030-01-15',8,7,:actor,:fingerprint,:result,true,"
                        "'2030-01-15T09:00:00+00:00') RETURNING id"
                    ),
                    {
                        "district": district_id,
                        "actor": actor_id,
                        "fingerprint": "b" * 64,
                        "result": '{"legacy": 2}',
                    },
                ).scalar_one()

            with engine.connect() as connection:
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
                command.check(config)
                rows = (
                    connection.execute(
                        text(
                            "SELECT id, service_area_id, revision, previous_revision, is_current, "
                            "reason, plan_state, superseded_by_revision "
                            "FROM day_plan_revisions ORDER BY id"
                        )
                    )
                    .mappings()
                    .all()
                )
                self.assertEqual([row["id"] for row in rows], [first_id, second_id])
                self.assertEqual([row["service_area_id"] for row in rows], [service_area_id] * 2)
                self.assertEqual([row["revision"] for row in rows], [1, 2])
                self.assertEqual([row["previous_revision"] for row in rows], [None, 1])
                self.assertEqual([row["is_current"] for row in rows], [False, True])
                self.assertEqual(rows[0]["superseded_by_revision"], 2)
                self.assertEqual(rows[1]["reason"], "plan_applied")
                self.assertEqual(
                    [row["plan_state"] for row in rows], [{"legacy": 1}, {"legacy": 2}]
                )
                connection.commit()

                command.downgrade(config, "0024")
                legacy = (
                    connection.execute(
                        text(
                            "SELECT id, district_id, revision, result "
                            "FROM day_plan_revisions ORDER BY id"
                        )
                    )
                    .mappings()
                    .all()
                )
                self.assertEqual([row["id"] for row in legacy], [first_id, second_id])
                self.assertEqual([row["district_id"] for row in legacy], [district_id] * 2)
                self.assertEqual([row["result"] for row in legacy], [{"legacy": 1}, {"legacy": 2}])
                connection.commit()

                command.upgrade(config, "head")
                command.check(config)
                self.assertEqual(
                    connection.execute(
                        text("SELECT count(*) FROM day_plan_revisions")
                    ).scalar_one(),
                    2,
                )

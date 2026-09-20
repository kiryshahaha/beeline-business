"""Round trips across migrated databases, including historical schema upgrades."""

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.db.session import get_session
from app.main import app
from app.modules.data_exchange.formats import parse_file, serialize
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

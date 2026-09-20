"""Ticket report downloads, filtering and role checks."""

import csv
import io
from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.db.session import get_session
from app.main import app
from app.modules.data_exchange.formats import parse_file, serialize
from app.modules.data_exchange.service import import_data
from generate_synthetic import generate_dataset
from tests.support import DatabaseTestCase


class TicketExportApiTests(DatabaseTestCase):
    """Exercise the file contract against a real isolated PostgreSQL schema."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        dataset = generate_dataset(seed=803, tickets=32, workers=8, days=2)
        normalized = parse_file(serialize(dataset, "csv"), "dataset.zip")
        with Session(cls.engine) as session:
            result = import_data(session, normalized)
        cls.ids = result["id_map"]

    def setUp(self):
        super().setUp()

        def override_session():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        self.addCleanup(app.dependency_overrides.pop, get_session)
        self.client = self.enterContext(TestClient(app))
        self.observer = self.auth(1)
        self.foreman = self.auth(3)
        self.worker = self.auth(9)

    def auth(self, source_id: int) -> dict[str, str]:
        user_id = self.ids["users"][str(source_id)]
        return {"Authorization": f"Bearer {create_access_token({'sub': str(user_id)})}"}

    def test_csv_export_returns_filtered_rows_and_download_headers(self):
        response = self.client.get(
            "/api/v1/reports/tickets/export",
            params={
                "format": "csv",
                "status": "completed",
                "city_id": self.ids["cities"]["1"],
            },
            headers=self.observer,
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"], "text/csv; charset=utf-8")
        self.assertIn('attachment; filename="tickets.csv"', response.headers["content-disposition"])

        rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
        self.assertGreater(len(rows), 0)
        self.assertEqual(
            set(rows[0]),
            {
                "id",
                "location_id",
                "title",
                "description",
                "work_type",
                "status",
                "visit_window_start",
                "visit_window_end",
                "planned_start_at",
                "planned_end_at",
                "estimated_duration_minutes",
                "actual_duration_minutes",
                "created_at",
                "updated_at",
                "assignee_ids",
                "city_id",
                "city",
                "district_id",
                "district",
                "street_id",
                "street",
                "building_id",
                "building_number",
                "block",
                "entrance_id",
                "entrance_number",
                "floor",
                "apartment",
                "latitude",
                "longitude",
                "address",
            },
        )
        self.assertTrue(all(row["status"] == "completed" for row in rows))
        self.assertTrue(all(row["city_id"] == str(self.ids["cities"]["1"]) for row in rows))

    def test_xlsx_export_returns_workbook_and_applies_district_filter(self):
        response = self.client.get(
            "/api/v1/reports/tickets/export",
            params={"format": "xlsx", "district_id": self.ids["districts"]["1"]},
            headers=self.observer,
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.headers["content-type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn(
            'attachment; filename="tickets.xlsx"', response.headers["content-disposition"]
        )

        workbook = load_workbook(BytesIO(response.content), read_only=True, data_only=True)
        self.addCleanup(workbook.close)
        self.assertEqual(workbook.sheetnames, ["tickets"])
        rows = list(workbook["tickets"].iter_rows(values_only=True))
        self.assertGreater(len(rows), 1)
        headers = list(rows[0])
        district_index = headers.index("district_id")
        self.assertTrue(all(row[district_index] == self.ids["districts"]["1"] for row in rows[1:]))

    def test_xlsx_is_default_format(self):
        response = self.client.get(
            "/api/v1/reports/tickets/export",
            params={"status": "planned"},
            headers=self.observer,
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(
            'attachment; filename="tickets.xlsx"', response.headers["content-disposition"]
        )

    def test_brigade_filter_is_applied(self):
        brigade_id = self.ids["brigades"]["1"]
        response = self.client.get(
            "/api/v1/reports/tickets/export",
            params={"format": "csv", "brigade_id": brigade_id},
            headers=self.observer,
        )

        self.assertEqual(response.status_code, 200, response.text)
        rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
        self.assertGreater(len(rows), 0)
        self.assertTrue(all(row["assignee_ids"] for row in rows))

    def test_export_requires_observer_and_valid_format(self):
        self.assertEqual(
            self.client.get("/api/v1/reports/tickets/export").status_code,
            401,
        )
        for headers in (self.foreman, self.worker):
            response = self.client.get(
                "/api/v1/reports/tickets/export",
                headers=headers,
            )
            self.assertEqual(response.status_code, 403, response.text)

        response = self.client.get(
            "/api/v1/reports/tickets/export",
            params={"format": "pdf"},
            headers=self.observer,
        )
        self.assertEqual(response.status_code, 422, response.text)

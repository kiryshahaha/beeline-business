"""Plan 5 acceptance package contracts, independent of planner outcomes."""

import csv
import json
import unittest
from collections import Counter
from datetime import date, time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sqlalchemy import text

from app.modules.data_exchange.formats import parse_file
from app.modules.data_exchange.service import import_data
from app.modules.source_import.classify import ClassificationError, classify_demand
from generate_acceptance_dataset import DATE, SEED, build_dataset, write_package
from tests.support import DatabaseTestCase
from verify_synthetic import verify_auxiliary_files


class AcceptanceDatasetTests(unittest.TestCase):
    def test_day_and_territory_counts(self):
        tables, scenarios = build_dataset()
        self.assertEqual(DATE, date(2030, 1, 15))
        self.assertEqual(len(tables["tickets"]), 48)
        self.assertEqual(len(tables["service_areas"]), 3)
        self.assertEqual(len(scenarios["roster_worker_ids"]), 12)
        self.assertEqual(len(tables["workers"]), 13)
        self.assertNotIn(scenarios["outside_roster_worker_id"], scenarios["roster_worker_ids"])
        self.assertEqual(
            Counter(t["phase"] for t in scenarios["tickets"]), {"planned": 36, "new": 12}
        )
        self.assertEqual(
            Counter(t["category"] for t in scenarios["tickets"] if t["phase"] == "new"),
            {"emergency": 6, "repair": 6},
        )
        cities = {city["id"]: city["name"] for city in tables["cities"]}
        buildings = {b["id"]: b for b in tables["buildings"]}
        locations = {loc["id"]: loc for loc in tables["locations"]}
        by_area = {}
        for ticket in tables["tickets"]:
            building = buildings[locations[ticket["location_id"]]["building_id"]]
            self.assertEqual(ticket["service_area_id"], building["service_area_id"])
            by_area.setdefault(ticket["service_area_id"], set()).add(cities[building["city_id"]])
        self.assertEqual(set(by_area), {101, 102, 103})
        self.assertTrue(all("Москва" in names and len(names) >= 2 for names in by_area.values()))
        tickets = {ticket["id"]: ticket for ticket in tables["tickets"]}
        ticket_building = buildings[locations[tickets[37]["location_id"]]["building_id"]]
        nearby_building = buildings[locations[tickets[2]["location_id"]]["building_id"]]
        remote_building = buildings[locations[tickets[38]["location_id"]]["building_id"]]
        self.assertNotEqual(ticket_building["service_area_id"], nearby_building["service_area_id"])
        self.assertEqual(cities[ticket_building["city_id"]], "Москва")
        self.assertEqual(cities[nearby_building["city_id"]], "Москва")
        self.assertLess(
            max(
                abs(
                    locations[tickets[37]["location_id"]][coordinate]
                    - locations[tickets[2]["location_id"]][coordinate]
                )
                for coordinate in ("latitude", "longitude")
            ),
            0.001,
        )
        self.assertEqual(remote_building["service_area_id"], tickets[38]["service_area_id"])
        self.assertNotEqual(cities[remote_building["city_id"]], "Москва")
        self.assertEqual(
            tables["tickets"][36]["received_at"].isoformat(), "2030-01-15T08:10:00+03:00"
        )
        no_slot = tables["tickets"][41]
        self.assertLess(
            (no_slot["visit_window_end"] - no_slot["visit_window_start"]).total_seconds(),
            no_slot["estimated_duration_minutes"] * 60,
        )
        self.assertEqual(len(tables["day_plan_revisions"]), 3)
        self.assertTrue(all(len(row["roster"]) == 4 for row in tables["day_plan_revisions"]))

    def test_emergency_windows_match_s14_cases(self):
        tickets = {ticket["id"]: ticket for ticket in build_dataset()[0]["tickets"]}
        early = tickets[43]
        later = tickets[45]

        self.assertEqual(
            (early["visit_window_start"].time(), early["visit_window_end"].time()),
            (time(10), time(12)),
        )
        self.assertEqual(
            (later["visit_window_start"].time(), later["visit_window_end"].time()),
            (time(12), time(14)),
        )

    def test_negative_hd_cases_match_server_classifier(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_package(root)
            with (root / "negative_tickets.csv").open(newline="", encoding="utf-8") as handle:
                cases = list(csv.DictReader(handle))
        self.assertEqual(len(cases), 5)
        for case in cases:
            with self.subTest(case=case["case_id"]):
                try:
                    category, _ = classify_demand(
                        case["request_type_hd"],
                        explicit_category=case["category"],
                        raise_on_unknown=case["strict"] == "true",
                    )
                    actual = category
                except ClassificationError as error:
                    actual = error.code
                self.assertEqual(actual, case["expected"])

    def test_formats_matrix_and_manifest_are_verifiable(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = write_package(root)
            self.assertEqual(manifest["seed"], SEED)
            self.assertEqual(manifest["timezone"], "Europe/Moscow")
            files = manifest["files"]
            self.assertEqual(set(files), {"dataset.zip", "dataset.xlsx"})
            csv = parse_file((root / "dataset.zip").read_bytes(), "dataset.zip")
            xlsx = parse_file((root / "dataset.xlsx").read_bytes(), "dataset.xlsx")
            self.assertEqual(csv, xlsx)
            self.assertEqual(len(csv["tickets"]), 48)
            road = json.loads((root / "road_matrix.json").read_text())
            self.assertEqual(road["source"], "deterministic_stub")
            self.assertNotEqual(
                road["travel_minutes"]["moscow_a"]["remote_a"],
                road["travel_minutes"]["remote_a"]["moscow_a"],
            )
            for name, metadata in {**files, **manifest["auxiliary_files"]}.items():
                import hashlib

                self.assertEqual(
                    hashlib.sha256((root / name).read_bytes()).hexdigest(), metadata["sha256"]
                )


class AcceptanceManifestTests(unittest.TestCase):
    def test_auxiliary_checksum_rejects_modified_road_matrix(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = write_package(root)
            self.assertEqual(verify_auxiliary_files(root, manifest), 3)
            matrix = root / "road_matrix.json"
            matrix.write_bytes(matrix.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
                verify_auxiliary_files(root, manifest)


class AcceptanceImportTests(DatabaseTestCase):
    def test_csv_import_then_xlsx_repeat_is_one_logical_dataset(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_package(root)
            csv = parse_file((root / "dataset.zip").read_bytes(), "dataset.zip")
            xlsx = parse_file((root / "dataset.xlsx").read_bytes(), "dataset.xlsx")
        with patch("app.modules.data_exchange.service.hash_password", return_value="test-only"):
            first = import_data(self.session, csv)
            second = import_data(self.session, xlsx)
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["fingerprint"], second["fingerprint"])
        self.assertEqual(
            self.session.execute(text("SELECT count(*) FROM tickets")).scalar_one(), 48
        )
        self.assertEqual(
            self.session.execute(text("SELECT count(*) FROM day_plan_revisions")).scalar_one(), 3
        )


if __name__ == "__main__":
    unittest.main()

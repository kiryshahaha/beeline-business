"""
T19: Business scenario sets validation.
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.data_exchange.formats import parse_file, serialize
from app.modules.data_exchange.service import import_data
from app.modules.planning.eligibility import prepare
from app.modules.planning.geometry import build_routes
from app.modules.planning.matrices import build_problem
from app.modules.planning.repository import load_snapshot
from app.modules.planning.schemas import PreviewRequest
from app.modules.planning.validation import validate_solution
from planning_scenarios import preview_request
from tests.planning_fakes import FeasiblePlanner, provider_factory
from tests.support import DatabaseTestCase
from tests.t19_generator import generate_t19_dataset


class T19BusinessScenariosTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.stamp = datetime(2030, 1, 14, 8, 0, tzinfo=UTC)

    def import_and_plan(self, data):
        csv_bytes = serialize(data, "csv")
        csv_parsed = parse_file(csv_bytes, "data.zip")
        with self.engine.connect() as connection:
            transaction = connection.begin()
            try:
                with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                    with patch(
                        "app.modules.data_exchange.service.hash_password", return_value="test-only"
                    ):
                        receipt = import_data(session, csv_parsed)

                    requests = []
                    for area_idx in range(1, 4):
                        area_id = 100 + area_idx
                        area_tickets = [
                            t for t in data["tickets"] if t["service_area_id"] == area_id
                        ]
                        area_workers = [
                            w for w in data["workers"] if w["service_area_id"] == area_id
                        ]
                        req_data = preview_request(
                            receipt, {"tickets": area_tickets, "workers": area_workers}
                        )
                        requests.append(PreviewRequest.model_validate(req_data))

                    routes = []
                    prepared_snapshots = []
                    for request in requests:
                        snapshot = load_snapshot(session, request)
                        prepared = prepare(snapshot, self.stamp)
                        prepared_snapshots.append(prepared)

                        settings = Settings()

                        async def run():
                            async with provider_factory() as provider:
                                problem, nodes = await build_problem(prepared, provider, settings)
                                solution = await FeasiblePlanner().solve(problem)
                                validate_solution(problem, solution)
                                result = await build_routes(
                                    prepared, problem, nodes, solution, provider, settings
                                )
                                return result.routes

                        routes.extend(asyncio.run(run()))

                    return prepared_snapshots, routes, receipt
            finally:
                transaction.rollback()

    def test_t19_base_scenario(self):
        data, metadata = generate_t19_dataset("base", seed=2001)
        prepared_snapshots, routes, receipt = self.import_and_plan(data)

        self.assertEqual(metadata["seed"], 2001)
        self.assertEqual(metadata["versions"]["schema"], "1.0")

        unassigned = {}
        workers = []
        for prepared in prepared_snapshots:
            for t in prepared["unassigned"]:
                unassigned[t["ticket_id"]] = t["reason"]["code"]
            workers.extend(prepared["workers"])

        self.assertTrue(isinstance(routes, list))
        self.assertGreater(len(workers), 0)

    def test_t19_edge_cases_scenario(self):
        data, metadata = generate_t19_dataset("edge_cases", seed=2002)
        prepared_snapshots, routes, receipt = self.import_and_plan(data)

        unassigned = {}
        for prepared in prepared_snapshots:
            for t in prepared["unassigned"]:
                unassigned[t["ticket_id"]] = t["reason"]["code"]

        self.assertTrue(isinstance(routes, list))
        # Validate invariants
        for old_t_id, expected_reason in metadata["invariants"].items():
            t_id = receipt["id_map"]["tickets"].get(str(old_t_id), old_t_id)
            if t_id not in unassigned:
                t_id = receipt["id_map"]["tickets"].get(int(old_t_id), old_t_id)
            self.assertIn(t_id, unassigned)
            self.assertEqual(unassigned[t_id], expected_reason)

    def test_t19_negative_scenario(self):
        data, metadata = generate_t19_dataset("negative", seed=2003)
        prepared_snapshots, routes, receipt = self.import_and_plan(data)

        unassigned = {}
        for prepared in prepared_snapshots:
            for t in prepared["unassigned"]:
                unassigned[t["ticket_id"]] = t["reason"]["code"]

        for old_t_id, expected_reason in metadata["invariants"].items():
            t_id = receipt["id_map"]["tickets"].get(str(old_t_id), old_t_id)
            if t_id not in unassigned:
                t_id = receipt["id_map"]["tickets"].get(int(old_t_id), old_t_id)
            self.assertIn(t_id, unassigned)
            self.assertEqual(unassigned[t_id], expected_reason)

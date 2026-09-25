"""All planning fixtures survive both parsers, real foreign keys and domain eligibility."""

import asyncio
from unittest.mock import patch

from sqlalchemy import func, select
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
from app.modules.tickets.models import Ticket
from planning_scenarios import NOW, SCENARIOS, generate_planning_dataset, preview_request
from tests.planning_fakes import FeasiblePlanner, provider_factory
from tests.support import DatabaseTestCase


class PlanningDatasetTests(DatabaseTestCase):
    def test_all_scenarios_have_valid_rows_relations_and_schedules(self):
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                data = generate_planning_dataset(scenario)
                csv = parse_file(serialize(data, "csv"), "data.zip")
                self.assertEqual(csv, parse_file(serialize(data, "xlsx"), "data.xlsx"))
                with self.engine.connect() as connection:
                    transaction = connection.begin()
                    try:
                        with Session(
                            bind=connection, join_transaction_mode="create_savepoint"
                        ) as session:
                            with patch(
                                "app.modules.data_exchange.service.hash_password",
                                return_value="test-only",
                            ):
                                receipt = import_data(session, csv)
                            self.assertEqual(
                                session.scalar(select(func.count()).select_from(Ticket)),
                                len(data["tickets"]),
                            )
                            request = PreviewRequest.model_validate(preview_request(receipt, data))
                            prepared = prepare(load_snapshot(session, request), NOW)
                            routes = asyncio.run(self.calculate(prepared))
                            self.assertTrue(routes)
                            if scenario == "rejections":
                                self.assertEqual(
                                    {r["reason"]["code"] for r in prepared["unassigned"]},
                                    {
                                        "ticket_not_planned",
                                        "unknown_work_type",
                                        "equipment_not_reserved",
                                        "outside_shift_horizon",
                                    },
                                )
                            else:
                                self.assertEqual(prepared["unassigned"], [])
                            if scenario == "duplicate_coordinates":
                                self.assertTrue(all(r["travel_minutes"] == 0 for r in routes))
                                self.assertEqual(sum(len(r["stops"]) for r in routes), 24)
                            if scenario == "night":
                                self.assertTrue(
                                    all(w["window"] == [1320, 1800] for w in prepared["workers"])
                                )
                            if scenario == "overload":
                                self.assertEqual(sum(len(r["stops"]) for r in routes), 24)
                    finally:
                        transaction.rollback()

    async def calculate(self, prepared):
        settings = Settings()
        async with provider_factory() as provider:
            problem, nodes = await build_problem(prepared, provider, settings)
            solution = await FeasiblePlanner().solve(problem)
            validate_solution(problem, solution)
            result = await build_routes(prepared, problem, nodes, solution, provider, settings)
            routes = result.routes
            return routes

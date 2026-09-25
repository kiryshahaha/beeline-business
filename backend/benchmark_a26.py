import asyncio
import sys
import time
import json
import logging
from unittest.mock import patch, MagicMock
from uuid import uuid4
from datetime import datetime, date, timezone

from datetime import datetime, date, timezone
import json
import time
import asyncio
from unittest.mock import patch
from app.modules.planning import service
from app.core.config import get_settings
from app.modules.planning.schemas import PreviewRequest
from app.modules.routing.client import AsyncGeoapifyRoutingClient
from app.modules.routing.schemas import RouteMatrixResult, RouteMatrixCell

class MockGeoapifyRoutingClient(AsyncGeoapifyRoutingClient):
    async def build_route_matrix(self, sources, targets, mode):
        self.telemetry.record_provider_request("matrix")
        if self.telemetry is not None:
            self.telemetry.record_operation("matrix", mode, cells=len(sources)*len(targets), source="mock")
        return RouteMatrixResult(
            cells=[[RouteMatrixCell(distance_meters=1000, duration_seconds=600) for _ in targets] for _ in sources]
        )
    async def build_route(self, origin, destination, mode):
        self.telemetry.record_provider_request("route")
        from app.modules.routing.schemas import RouteResult
        return RouteResult(distance_meters=1000, duration_seconds=600, geometry={"type": "MultiLineString", "coordinates": [[list(origin), list(destination)]]})

class MockPlanner:
    async def solve(self, problem):
        import sys, os
        sys.path.insert(0, os.path.abspath("./tests"))
        from test_planning_reliability import FeasiblePlanner
        return await FeasiblePlanner().solve(problem)

async def measure(tickets_count, workers_count):
    settings = get_settings()
    settings.planning_max_tickets = 1000
    settings.planning_max_matrix_cells_total = 1000000
    
    epoch = datetime(2026, 9, 26, 9, tzinfo=timezone.utc)
    prepared = {
        "epoch": epoch,
        "horizon": 120,
        "policy": service.execution_policy(settings),
        "open_end": False,
        "route_end": "return_to_start",
        "unassigned": [],
        "excluded_workers": [],
        "workers": [],
        "tickets": [],
        "locations": {}
    }
    
    for i in range(workers_count):
        loc_id = i % 3 + 1
        prepared["workers"].append({
            "user_id": i + 1,
            "worker_id": i + 1,
            "office_id": 1,
            "location_id": loc_id,
            "skill_ids": [],
            "profile": ["drive", "walk", "scooter", "bicycle"][i % 4],
            "transport_type": "car",
            "window": [0, 120],
        })
        prepared["locations"][loc_id] = {"longitude": 37.0 + (i % 3) * 0.1, "latitude": 55.0 + (i % 3) * 0.1}

    for i in range(tickets_count):
        loc_id = i + 1000
        prepared["tickets"].append({
            "id": i + 100,
            "location_id": loc_id,
            "window": [0, 110],
            "duration": 10,
            "duration_source": "ticket_estimate",
            "allowed": list(range(workers_count)),
            "category": "repair",
            "priority": 3,
            "received_at": epoch,
            "sla_deadline_at": None,
            "deadline_at": None,
            "rejected": [],
            "allocations": [],
        })
        prepared["locations"][loc_id] = {"longitude": 38.0 + i * 0.01, "latitude": 56.0 + i * 0.01}

    req = PreviewRequest(
        route_date=date(2026, 9, 26),
        ticket_ids=[t["id"] for t in prepared["tickets"]],
        worker_ids=[w["worker_id"] for w in prepared["workers"]]
    )
    
    provider = MockGeoapifyRoutingClient("fake")
    planner = MockPlanner()
    
    start_time = time.perf_counter()
    with patch("app.modules.planning.service.prepare", return_value=prepared):
        with patch("app.modules.planning.service.Session"):
            with patch.object(service, "read_snapshot", return_value={"request": req.model_dump(mode="json"), "tickets": prepared["tickets"], "workers": prepared["workers"], "planning_policy": prepared["policy"].model_dump(mode="json")}):
                with patch.object(service, "visit_factors", return_value=(0, 0)):
                    plan = await service.preview(
                        engine=None, 
                        request=req, 
                        actor=1, 
                        settings=settings, 
                        provider_factory=lambda: provider, 
                        planner=planner,
                        clock=lambda: epoch
                    )
            
    total_time = time.perf_counter() - start_time
    snap_size_kb = len(json.dumps(prepared, default=str)) / 1024.0
    
    metrics = plan["metrics"]["routing"]
    u = int((metrics["matrix_cells"] / 4)**0.5)
    
    return {
        "tickets": tickets_count,
        "workers": workers_count,
        "snap_kb": snap_size_kb,
        "unique_coords": u,
        "matrix_cells": metrics["matrix_cells"],
        "http_blocks": metrics["provider_requests"].get("matrix", 0),
        "geom_time_ms": metrics["stages"].get("route_fetch", {}).get("duration_ms", 0),
        "total_time_s": total_time
    }

async def run_all():
    scenarios = [(10, 10), (25, 12), (50, 15), (100, 15)]
    results = []
    for t, w in scenarios:
        res = await measure(t, w)
        results.append(res)
        
    with open("../docs/T18_BUDGET_A26.md", "w") as f:
        f.write("# T18: Measured Budgets A26\n\n")
        f.write("| Tickets | Workers | Snapshot (KB) | Unique Coords | Matrix Cells (4 profs) | HTTP Matrix Blocks | Geom Time (ms) | Total Time (s) |\n")
        f.write("|---------|---------|---------------|---------------|------------------------|--------------------|----------------|----------------|\n")
        for r in results:
            f.write(f"| {r['tickets']} | {r['workers']} | {r['snap_kb']:.1f} | {r['unique_coords']} | {r['matrix_cells']} | {r['http_blocks']} | {r['geom_time_ms']} | {r['total_time_s']:.2f} |\n")
    print("Done!")

if __name__ == "__main__":
    asyncio.run(run_all())

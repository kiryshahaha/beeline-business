"""One internal HTTP call; no database sessions or user credentials cross this boundary."""

import httpx
from pydantic import ValidationError

from app.core.config import Settings
from app.core.http_limits import bounded_request
from app.modules.planning.errors import PlanningError
from app.modules.planning.solver_contract import SolveRequest, SolveResponse


class PlannerClient:
    def __init__(self, settings: Settings, *, transport=None):
        self.settings = settings
        self.transport = transport

    async def solve(self, problem: SolveRequest) -> SolveResponse:
        settings = self.settings
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(
                    settings.planner_read_timeout_seconds,
                    connect=settings.planner_connect_timeout_seconds,
                ),
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                response = await bounded_request(
                    client,
                    "POST",
                    settings.planner_base_url.rstrip("/") + "/api/v1/solve",
                    headers={"X-Planner-Token": settings.planner_service_token.get_secret_value()},
                    json=problem.model_dump(mode="json"),
                )
        except ValueError as error:
            raise PlanningError("planner_invalid_response", 502) from error
        except httpx.TimeoutException as error:
            raise PlanningError("planner_timeout", 504) from error
        except httpx.RequestError as error:
            raise PlanningError("planner_unavailable", 503) from error
        if response.status_code != 200:
            raise PlanningError("planner_failure", 502)
        try:
            return SolveResponse.model_validate(response.json())
        except (ValueError, ValidationError) as error:
            raise PlanningError("planner_invalid_response", 502) from error

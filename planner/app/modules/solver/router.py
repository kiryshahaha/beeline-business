"""Authenticated internal planner contract; user JWTs never enter the solver."""

import os
import secrets
from threading import BoundedSemaphore
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from app.modules.solver.schemas import SolveRequest, SolveResponse
from app.modules.solver.service import solve

_solve_slots = BoundedSemaphore(2)

router = APIRouter(prefix="/api/v1/solve", tags=["solver"])


def require_service_token(x_planner_token: Annotated[str | None, Header()] = None):
    expected = os.getenv("PLANNER_SERVICE_TOKEN", "")
    if not expected:
        raise HTTPException(503, "Planner service token is not configured")
    if not x_planner_token or not secrets.compare_digest(x_planner_token, expected):
        raise HTTPException(401, "Invalid planner service token")


@router.post("", response_model=SolveResponse, dependencies=[Depends(require_service_token)])
def solve_vrptw(data: SolveRequest) -> SolveResponse:
    if not _solve_slots.acquire(blocking=False):
        raise HTTPException(503, "Planner is busy", headers={"Retry-After": "5"})
    try:
        return solve(data)
    finally:
        _solve_slots.release()

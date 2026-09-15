"""API router for the solver service."""

from fastapi import APIRouter

from app.modules.solver.schemas import SolveRequest, SolveResponse
from app.modules.solver.service import VRPTWSolver

router = APIRouter(prefix="/api/v1/solve", tags=["solver"])


@router.post("", response_model=SolveResponse)
def solve_vrptw(data: SolveRequest) -> SolveResponse:
    """Solve the Vehicle Routing Problem with Time Windows."""
    solver = VRPTWSolver(data)
    return solver.solve()

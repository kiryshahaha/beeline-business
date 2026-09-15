"""FastAPI entry point for the solver service."""

from fastapi import FastAPI

from app.modules.solver.router import router as solver_router

app = FastAPI(
    title="VRPTW Solver Service",
    description="Stateless OR-Tools microservice for WFM route optimization.",
    version="1.0.0",
)

app.include_router(solver_router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Liveness check."""
    return {"status": "ok"}

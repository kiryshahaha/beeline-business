"""Validation schemas for the routing solver."""

from typing import Literal

from pydantic import BaseModel, Field


class Step(BaseModel):
    node: int = Field(description="Index of the node visited")
    arrival_time: int = Field(description="Arrival time at the node in minutes")


class Route(BaseModel):
    vehicle_id: int = Field(description="ID of the vehicle")
    steps: list[Step] = Field(default_factory=list, description="Sequence of visited nodes")


class SolveResponse(BaseModel):
    status: Literal["OPTIMAL", "FEASIBLE", "INFEASIBLE", "NOT_SOLVED"] = Field(description="Solver status")
    routes: list[Route] = Field(default_factory=list, description="Computed routes for vehicles")
    dropped_nodes: list[int] = Field(default_factory=list, description="Indices of nodes that were dropped")
    total_cost: int = Field(description="Total cost of the solution")


class SolveRequest(BaseModel):
    num_vehicles: int = Field(gt=0, description="Number of available vehicles")
    starts: list[int] = Field(description="Start nodes for each vehicle")
    ends: list[int] = Field(description="End nodes for each vehicle")
    time_matrix: list[list[int]] = Field(description="Travel time matrix between all nodes")
    time_windows: list[list[int]] = Field(description="Time windows [start, end] for each node")
    service_times: list[int] = Field(description="Service duration for each node")
    allowed_vehicles: dict[str, list[int]] | None = Field(
        default=None, description="Mapping of node index to list of allowed vehicle IDs"
    )
    penalties: list[int] = Field(description="Penalty cost for dropping each node")

"""Validation schemas for the routing solver."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Step(BaseModel):
    node: int = Field(description="Index of the node visited")
    arrival_time: int = Field(description="Arrival time at the node in minutes")


class Route(BaseModel):
    vehicle_id: int = Field(description="ID of the vehicle")
    distance: int = Field(default=0, description="Total distance (or proxy distance) for the route")
    steps: list[Step] = Field(default_factory=list, description="Sequence of visited nodes")


class SolveResponse(BaseModel):
    status: Literal["OPTIMAL", "FEASIBLE", "INFEASIBLE", "NOT_SOLVED"] = Field(description="Solver status")
    routes: list[Route] = Field(default_factory=list, description="Computed routes for vehicles")
    dropped_nodes: list[int] = Field(default_factory=list, description="Indices of nodes that were dropped")
    total_cost: int = Field(description="Total cost of the solution")
    total_distance: int = Field(default=0, description="Total distance of all routes")


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

    # Optional distance matrix
    distance_matrix: list[list[int]] | None = Field(default=None, description="Distance matrix between all nodes")

    # Algorithm configuration parameters
    search_time_limit_s: int = Field(default=3, description="Time limit for the solver in seconds")
    slack_max: int = Field(default=120, description="Max waiting time at a node")
    time_capacity: int = Field(default=14400, description="Max time capacity (horizon) for a vehicle")
    vehicle_fixed_cost: int = Field(default=100000, description="Cost of using a vehicle to minimize workforce")

    @model_validator(mode="after")
    def validate_dimensions(self) -> "SolveRequest":
        n_nodes = len(self.time_matrix)
        if len(self.starts) != self.num_vehicles:
            raise ValueError(f"Length of starts ({len(self.starts)}) must match num_vehicles ({self.num_vehicles})")
        if len(self.ends) != self.num_vehicles:
            raise ValueError(f"Length of ends ({len(self.ends)}) must match num_vehicles ({self.num_vehicles})")
        
        for row in self.time_matrix:
            if len(row) != n_nodes:
                raise ValueError("time_matrix must be square")
                
        if len(self.time_windows) != n_nodes:
            raise ValueError(f"Length of time_windows ({len(self.time_windows)}) must match number of nodes ({n_nodes})")
        if len(self.service_times) != n_nodes:
            raise ValueError(f"Length of service_times ({len(self.service_times)}) must match number of nodes ({n_nodes})")
            
        if self.distance_matrix is not None:
            if len(self.distance_matrix) != n_nodes:
                raise ValueError(f"Length of distance_matrix ({len(self.distance_matrix)}) must match number of nodes ({n_nodes})")
            for row in self.distance_matrix:
                if len(row) != n_nodes:
                    raise ValueError("distance_matrix must be square")
                    
        return self

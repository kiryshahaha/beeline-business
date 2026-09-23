"""Bounded wire contract. Kept identical to backend's solver_contract.py."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Minute = Annotated[int, Field(strict=True, ge=0, le=2880)]
Index = Annotated[int, Field(strict=True, ge=0, le=99)]
Cost = Annotated[int, Field(strict=True, ge=0, le=1_000_000_000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Matrix(StrictModel):
    time_minutes: list[list[Cost | None]] = Field(min_length=1, max_length=100)
    distance_meters: list[list[Cost | None]] = Field(min_length=1, max_length=100)


class SolveRequest(StrictModel):
    contract_version: Literal[1] = 1
    policy_version: Literal[1] = 1
    num_vehicles: Annotated[int, Field(strict=True, ge=1, le=20)]
    starts: list[Index]
    ends: list[Index]
    vehicle_profiles: list[str]
    vehicle_time_windows: list[tuple[Minute, Minute]]
    matrices: dict[str, Matrix] = Field(min_length=1, max_length=4)
    time_windows: list[tuple[Minute, Minute]]
    service_times: list[Minute]
    allowed_vehicles: dict[str, list[Annotated[int, Field(strict=True, ge=0, le=19)]]]
    penalties: list[Cost]
    time_capacity: Annotated[int, Field(strict=True, ge=1, le=2880)]
    slack_max: Minute
    vehicle_fixed_cost: Annotated[int, Field(strict=True, ge=0, le=0)] = 0
    search_time_limit_s: Annotated[int, Field(strict=True, ge=1, le=10)] = 5

    @model_validator(mode="after")
    def validate_problem(self) -> Self:
        v = self.num_vehicles
        n = len(next(iter(self.matrices.values())).time_minutes)
        if any(
            len(a) != v
            for a in (self.starts, self.ends, self.vehicle_profiles, self.vehicle_time_windows)
        ):
            raise ValueError("Vehicle array dimensions must match num_vehicles")
        if len(set(self.starts)) != v or len(set(self.ends)) != v:
            raise ValueError("Every vehicle needs its own start and end depot node")
        if any(i >= n for i in (*self.starts, *self.ends)):
            raise ValueError("Depot index outside matrices")
        if any(p not in self.matrices for p in self.vehicle_profiles):
            raise ValueError("Unknown vehicle matrix profile")
        if any(len(a) != n for a in (self.time_windows, self.service_times, self.penalties)):
            raise ValueError("Node array dimensions must match matrices")
        if any(
            a > b or b > self.time_capacity
            for a, b in (*self.time_windows, *self.vehicle_time_windows)
        ):
            raise ValueError("Invalid time window or horizon")
        if self.slack_max > self.time_capacity:
            raise ValueError("Waiting exceeds horizon")
        depots = set(self.starts) | set(self.ends)
        if any(self.service_times[i] or self.penalties[i] for i in depots):
            raise ValueError("Depots cannot have service or dropping costs")
        tasks = set(range(n)) - depots
        if set(self.allowed_vehicles) != {str(i) for i in tasks}:
            raise ValueError("Explicit eligibility is required for every task, only tasks")
        for allowed in self.allowed_vehicles.values():
            if len(set(allowed)) != len(allowed) or any(i >= v for i in allowed):
                raise ValueError("Invalid or duplicate allowed vehicle")
        for matrix in self.matrices.values():
            for values in (matrix.time_minutes, matrix.distance_meters):
                if len(values) != n or any(len(row) != n for row in values):
                    raise ValueError("All matrices must have the same square shape")
                if any(values[i][i] != 0 for i in range(n)):
                    raise ValueError("Matrix diagonal must be zero")
            for i in range(n):
                for j in range(n):
                    if (matrix.time_minutes[i][j] is None) != (
                        matrix.distance_meters[i][j] is None
                    ):
                        raise ValueError("Unreachable time and distance must both be null")
        return self


class Step(StrictModel):
    node: Index
    arrival_time: Minute


class Route(StrictModel):
    vehicle_id: Annotated[int, Field(strict=True, ge=0, le=19)]
    steps: list[Step] = Field(min_length=2, max_length=72)
    distance: Cost
    travel_minutes: Cost
    service_minutes: Cost
    waiting_minutes: Cost


class SolveResponse(StrictModel):
    contract_version: Literal[1] = 1
    status: Literal["FEASIBLE", "OPTIMAL", "INFEASIBLE", "NOT_SOLVED"]
    solver_status_code: Annotated[int, Field(strict=True, ge=0, le=100)]
    routes: list[Route] = Field(default_factory=list, max_length=20)
    dropped_nodes: list[Index] = Field(default_factory=list, max_length=100)
    total_cost: Cost = 0
    total_distance: Cost = 0

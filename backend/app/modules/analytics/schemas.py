"""Schemas for analytics query parameters and responses."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class AnalyticsPeriod(StrEnum):
    TODAY = "today"
    WEEK = "week"
    MONTH = "month"


class TicketsSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    open: int
    assigned: int
    in_progress: int
    completed: int


class BrigadeWorkloadItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brigade_name: str
    active_tickets: int
    completed_today: int

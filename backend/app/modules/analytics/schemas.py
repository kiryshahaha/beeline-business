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

"""Acceptance HTTP app with a fixed test day; routing and native planner stay separate."""

from datetime import UTC, datetime

from app.modules.planning.router import get_clock
from testing.backend_app import app

ACCEPTANCE_NOW = datetime(2030, 1, 15, 5, 20, tzinfo=UTC)
app.dependency_overrides[get_clock] = lambda: lambda: ACCEPTANCE_NOW

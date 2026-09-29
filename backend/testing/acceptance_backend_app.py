"""Acceptance HTTP app with a fixed test day; routing and native planner stay separate."""

import os
from datetime import UTC, datetime
from pathlib import Path

from app.modules.planning.router import get_clock
from testing.backend_app import app

ACCEPTANCE_NOW = datetime(2030, 1, 15, 5, 20, tzinfo=UTC)


def acceptance_now():
    clock_file = os.getenv("ACCEPTANCE_CLOCK_FILE")
    if clock_file:
        return datetime.fromisoformat(
            Path(clock_file).read_text(encoding="utf-8").strip()
        ).astimezone(UTC)
    return ACCEPTANCE_NOW


app.dependency_overrides[get_clock] = lambda: acceptance_now

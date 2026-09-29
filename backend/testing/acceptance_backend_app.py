"""Acceptance HTTP app with a fixed test day; routing and native planner stay separate."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Request

from app.modules.planning.router import get_clock
from testing.backend_app import app

ACCEPTANCE_NOW = datetime(2030, 1, 15, 5, 20, tzinfo=UTC)
ACCEPTANCE_DAY_START = datetime(2030, 1, 15, tzinfo=ZoneInfo("Europe/Moscow"))
ACCEPTANCE_DAY_END = ACCEPTANCE_DAY_START + timedelta(days=1)


def acceptance_now():
    clock_file = os.getenv("ACCEPTANCE_CLOCK_FILE")
    if clock_file:
        return datetime.fromisoformat(
            Path(clock_file).read_text(encoding="utf-8").strip()
        ).astimezone(UTC)
    return ACCEPTANCE_NOW


def acceptance_clock(request: Request):
    """A request may state its own moment of the test day; otherwise the shared clock."""
    header = request.headers.get("X-Acceptance-Now")
    if header is None:
        return acceptance_now
    now = datetime.fromisoformat(header)
    if now.tzinfo is None or not ACCEPTANCE_DAY_START <= now < ACCEPTANCE_DAY_END:
        raise ValueError("Invalid acceptance clock")
    return lambda: now.astimezone(UTC)


app.dependency_overrides[get_clock] = acceptance_clock

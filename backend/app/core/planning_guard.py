"""Serialize short domain mutations; never hold this lock across network calls.

One transaction-scoped advisory lock covers the snapshot check of apply, assignment
changes and every warehouse operation, because they touch overlapping rows (tickets,
workers, office stock) that a finer key cannot separate without new races. It stays
global; what is bounded is the wait. Holding time is short — apply writes a prepared
result and no network call runs under the lock — so a long wait means contention or a
stuck transaction, and the caller gets a clear retryable error instead of hanging.
"""

import logging
import time

from psycopg.errors import LockNotAvailable
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core import oplog

PLANNING_LOCK_KEY = (17321, 1)
DEFAULT_LOCK_TIMEOUT_SECONDS = 5.0
# A wait above this is worth a warning even when the lock was eventually granted.
SLOW_WAIT_SECONDS = 1.0


class PlanningLockTimeout(Exception):
    """The shared planning lock was not granted within the configured timeout."""

    code = "planning_lock_timeout"

    def __init__(self, waited_ms: float, timeout_ms: int):
        super().__init__("Planning mutation lock was not granted in time")
        self.waited_ms = round(waited_ms)
        self.timeout_ms = timeout_ms


def _timeout_seconds() -> float:
    from app.core.config import get_settings

    try:
        return get_settings().planning_lock_timeout_seconds
    except ValidationError:
        # Scripts without full settings (seeding, migrations) keep the historical bound.
        return DEFAULT_LOCK_TIMEOUT_SECONDS


def lock_planning_mutation(session: Session, *, timeout_seconds: float | None = None) -> None:
    timeout_ms = round(1000 * (timeout_seconds or _timeout_seconds()))
    # lock_timeout stays in force for the row locks the transaction takes afterwards.
    session.execute(
        text("SELECT set_config('lock_timeout', :value, true)"), {"value": f"{timeout_ms}ms"}
    )
    started = time.perf_counter()
    try:
        session.execute(
            text("SELECT pg_advisory_xact_lock(:space, :key)"),
            {
                "space": PLANNING_LOCK_KEY[0],
                "key": PLANNING_LOCK_KEY[1],
            },
        )
    except OperationalError as error:
        if not isinstance(error.orig, LockNotAvailable):
            raise
        waited_ms = (time.perf_counter() - started) * 1000
        oplog.log(
            "planning.lock_timeout", logging.WARNING, waited_ms=waited_ms, timeout_ms=timeout_ms
        )
        raise PlanningLockTimeout(waited_ms, timeout_ms) from error
    waited = time.perf_counter() - started
    oplog.record_stage("lock_wait", waited)
    if waited >= SLOW_WAIT_SECONDS:
        oplog.log(
            "planning.lock_wait_slow",
            logging.WARNING,
            waited_ms=waited * 1000,
            timeout_ms=timeout_ms,
        )

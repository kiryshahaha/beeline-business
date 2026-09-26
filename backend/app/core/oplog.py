"""Structured operation log: one JSON line per operation, identifiers and numbers only.

Stage durations are collected in a per-request trace (a context variable, so worker
threads started with `asyncio.to_thread` add to the same trace) and written once when
the operation ends. What reaches the log is filtered twice: keys that could carry a
secret or personal data are dropped whatever their value, and a string value is kept
only if it looks like an identifier or a code. An access token, a client's address or
a ticket's text therefore cannot end up in the log even by mistake.
"""

import functools
import json
import logging
import re
import sys
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, date, datetime
from uuid import UUID

LOGGER_NAME = "beeline.ops"
logger = logging.getLogger(LOGGER_NAME)

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_trace: ContextVar[dict | None] = ContextVar("operation_trace", default=None)

_FORBIDDEN_KEY = re.compile(
    r"token|password|secret|authorization|cookie|address|street|apartment|phone|"
    r"title|description|comment|text|name|email|latitude|longitude|geojson|body",
    re.IGNORECASE,
)
# Free strings pass only as lowercase codes and ids (UUIDs, "plan_stale") or short
# uppercase enum values ("FEASIBLE"). Tokens are base64 with mixed case, so they never do.
_SAFE_STRING = re.compile(r"[a-z0-9_.:\-]{1,64}|[A-Z_]{1,32}")
_REQUEST_ID = re.compile(r"[a-z0-9\-]{8,64}")


def _safe(value):
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float):
        return round(value, 3) if isinstance(value, float) else value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, str):
        return value if _SAFE_STRING.fullmatch(value) else None
    if isinstance(value, dict):
        return {
            str(key): cleaned
            for key, item in value.items()
            if not _FORBIDDEN_KEY.search(str(key)) and (cleaned := _safe(item)) is not None
        }
    if isinstance(value, list | tuple):
        items = [cleaned for item in value[:50] if (cleaned := _safe(item)) is not None]
        return items
    return None


def safe_fields(fields: dict) -> dict:
    return _safe(fields)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            "event": record.getMessage(),
            **getattr(record, "fields", {}),
        }
        return json.dumps(entry, ensure_ascii=False, separators=(",", ":"))


def configure(level: str = "INFO") -> None:
    """Write operation records as JSON lines to stdout; safe to call repeatedly."""
    if not any(isinstance(handler.formatter, JsonFormatter) for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(level.upper())
    logger.propagate = False
    # logging.config.fileConfig disables loggers that existed before it ran.
    logger.disabled = False


def request_id() -> str | None:
    return _request_id.get()


def bind_request_id(value: str | None) -> str:
    """Use a well-formed incoming X-Request-ID, otherwise generate one."""
    rid = value.lower() if value and _REQUEST_ID.fullmatch(value.lower()) else uuid.uuid4().hex
    _request_id.set(rid)
    return rid


def log(event: str, level: int = logging.INFO, **fields) -> None:
    if not logger.isEnabledFor(level):
        return
    payload = safe_fields({"request_id": request_id(), **fields})
    logger.log(level, event, extra={"fields": payload})


@contextmanager
def operation(event: str, **fields):
    """Trace one operation; the caller adds result identifiers to the yielded dict."""
    trace = {"stages": {}}
    token = _trace.set(trace)
    started = time.perf_counter()
    outcome = "ok"
    try:
        yield fields
    except BaseException as error:
        outcome = getattr(error, "code", None) or type(error).__name__
        raise
    finally:
        _trace.reset(token)
        log(
            event,
            logging.INFO if outcome == "ok" else logging.WARNING,
            outcome=outcome,
            duration_ms=(time.perf_counter() - started) * 1000,
            stages=trace["stages"],
            **fields,
        )


def record_stage(name: str, elapsed_seconds: float) -> None:
    """Add a stage duration to the current trace, if an operation is being traced."""
    trace = _trace.get()
    if trace is None:
        return
    stage = trace["stages"].setdefault(name, {"calls": 0, "duration_ms": 0.0})
    stage["calls"] += 1
    stage["duration_ms"] += max(0.0, elapsed_seconds * 1000)


@contextmanager
def stage(name: str):
    started = time.perf_counter()
    try:
        yield
    finally:
        record_stage(name, time.perf_counter() - started)


def merge_stages(stages: dict) -> None:
    """Add stage totals measured elsewhere (e.g. routing telemetry) to the current trace."""
    trace = _trace.get()
    if trace is None:
        return
    for name, metrics in (stages or {}).items():
        stage = trace["stages"].setdefault(name, {"calls": 0, "duration_ms": 0.0})
        stage["calls"] += int(metrics.get("calls", 0))
        stage["duration_ms"] += float(metrics.get("duration_ms", 0.0))


def timed(name: str):
    """Decorator form of `stage` for a synchronous function."""

    def decorate(function):
        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            with stage(name):
                return function(*args, **kwargs)

        return wrapper

    return decorate

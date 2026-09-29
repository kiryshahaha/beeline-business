"""Shared emergency response deadline calculations for planning previews."""

from datetime import datetime
from math import ceil


def _datetime(value):
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def response_sla(received_at, response_deadline_at, service_start_at) -> dict:
    """Return response timing against the ticket's explicit response deadline."""
    received = _datetime(received_at)
    deadline = _datetime(response_deadline_at)
    start = _datetime(service_start_at)
    response_minutes = (
        ceil((start - received).total_seconds() / 60)
        if start is not None and received is not None
        else None
    )
    target_minutes = (
        ceil((deadline - received).total_seconds() / 60)
        if deadline is not None and received is not None
        else None
    )
    timeline_valid = start >= received if start is not None and received is not None else None
    deadline_met = (
        timeline_valid and start <= deadline
        if start is not None and deadline is not None and timeline_valid is not None
        else None
    )
    lateness_minutes = (
        max(0, ceil((start - deadline).total_seconds() / 60))
        if start is not None and deadline is not None and timeline_valid
        else None
    )
    if start is None or received is None or deadline is None:
        status = "unknown"
    elif not timeline_valid:
        status = "invalid_timeline"
    elif deadline_met:
        status = "on_time" if response_minutes <= 60 else "acceptable"
    else:
        status = "violated"

    return {
        "reaction_to_service_start_minutes": response_minutes,
        "response_deadline_at": deadline,
        "response_target_minutes": target_minutes,
        "response_deadline_met": deadline_met,
        "response_lateness_minutes": lateness_minutes,
        "response_timeline_valid": timeline_valid,
        "response_sla_status": status,
        "within_60_minutes_to_service_start": (
            0 <= response_minutes <= 60 if response_minutes is not None else None
        ),
        "within_120_minutes_to_service_start": (
            0 <= response_minutes <= 120 if response_minutes is not None else None
        ),
    }

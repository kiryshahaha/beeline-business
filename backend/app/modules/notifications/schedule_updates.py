"""Transient cross-process signals that make schedule screens reload their data."""

from sqlalchemy import text
from sqlalchemy.orm import Session

SCHEDULE_UPDATE_CHANNEL = "beeline_schedule_updated"
SCHEDULE_UPDATED_EVENT = {"type": "schedule_updated"}


def publish_schedule_updated(session: Session) -> None:
    """Queue a signal for the transaction that publishes the new schedule revision."""
    session.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": SCHEDULE_UPDATE_CHANNEL, "payload": "schedule_updated"},
    )

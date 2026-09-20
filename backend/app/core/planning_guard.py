"""Serialize short domain mutations; never hold this lock across network calls."""

from sqlalchemy import text
from sqlalchemy.orm import Session


def lock_planning_mutation(session: Session) -> None:
    session.execute(text("SET LOCAL lock_timeout = '5s'"))
    session.execute(text("SELECT pg_advisory_xact_lock(17321, 1)"))

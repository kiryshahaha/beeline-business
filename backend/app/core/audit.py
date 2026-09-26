"""Tell the database who is changing an assignment and why.

`tickets_record_assignment` (migration 0027) writes every assignee change on its own,
so history does not depend on each caller remembering to log it. What only the
application knows — the acting user and the path the change came through — travels in
transaction-local settings that the trigger reads.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

ASSIGNMENT_SOURCES = frozenset({"manual", "plan", "line_status", "direct"})


def set_assignment_origin(session: Session, *, actor_id: int | None, source: str) -> None:
    """Attribute the assignment changes that follow in this transaction.

    The settings are transaction-local, so they vanish on commit or rollback, including
    the rollback of a savepoint. Call it before each assignment write: a later write in
    the same transaction through another path sets its own origin.
    """
    if source not in ASSIGNMENT_SOURCES:
        raise ValueError(f"Unknown assignment source: {source}")
    session.execute(
        text(
            "SELECT set_config('app.actor_id', :actor_id, true), "
            "set_config('app.assignment_source', :source, true)"
        ),
        {"actor_id": "" if actor_id is None else str(actor_id), "source": source},
    )

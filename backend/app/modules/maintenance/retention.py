"""What is deleted, what is kept forever, and how cleanup avoids racing with apply.

Deleted:
- previews that were never applied and expired more than `preview_retention` ago —
  their input and result snapshots are the largest rows in the database and nothing
  can use them any more (apply refuses an expired preview);
- notification deliveries older than `notification_retention` once both channels are
  settled; a value of 0 keeps them forever.

Kept forever: applied plans with their snapshots, saved routes, day-plan revisions,
work events, assignment history, day states and import receipts — the history that
explains why the day looks the way it does.

Each batch runs in its own short transaction under the shared planning lock, so a
concurrent apply either sees the preview or gets `plan_not_found`, never half of it.
"""

from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.core.planning_guard import lock_planning_mutation

BATCH_SIZE = 500
# Only one process runs a cleanup pass at a time; the others skip it.
CLEANUP_LOCK_KEY = (17321, 3)

EXPIRED_PREVIEWS_SQL = """
    SELECT plan.id
    FROM planning_plans AS plan
    WHERE plan.state <> 'applied'
      AND plan.expires_at < :cutoff
      AND NOT EXISTS (SELECT 1 FROM planning_plan_routes AS route WHERE route.plan_id = plan.id)
      AND NOT EXISTS (
          SELECT 1 FROM day_plan_revisions AS revision WHERE revision.plan_id = plan.id
      )
    ORDER BY plan.expires_at, plan.id
    LIMIT :batch
"""

SETTLED_NOTIFICATIONS_SQL = """
    SELECT event.id
    FROM notification_events AS event
    WHERE event.created_at < :cutoff
      AND event.push_delivered_at IS NOT NULL
      AND (event.websocket_delivered_at IS NOT NULL OR event.websocket_missed_at IS NOT NULL)
    ORDER BY event.id
    LIMIT :batch
"""

TARGETS = {
    "expired_previews": ("planning_plans", EXPIRED_PREVIEWS_SQL),
    "settled_notifications": ("notification_events", SETTLED_NOTIFICATIONS_SQL),
}


def _cutoffs(
    now: datetime, preview_retention: timedelta, notification_retention: timedelta | None
) -> dict[str, datetime]:
    cutoffs = {"expired_previews": now - preview_retention}
    if notification_retention:
        cutoffs["settled_notifications"] = now - notification_retention
    return cutoffs


def count_candidates(
    session: Session,
    *,
    now: datetime,
    preview_retention: timedelta,
    notification_retention: timedelta | None,
) -> dict[str, int]:
    """Dry run: how many rows each rule would delete now."""
    counts = dict.fromkeys(TARGETS, 0)
    for name, cutoff in _cutoffs(now, preview_retention, notification_retention).items():
        _table, query = TARGETS[name]
        counts[name] = session.execute(
            text(f"SELECT count(*) FROM ({query}) AS candidate"),
            {"cutoff": cutoff, "batch": 2_147_483_647},
        ).scalar_one()
    return counts


def purge_batch(session: Session, name: str, cutoff: datetime, batch: int = BATCH_SIZE) -> int:
    """Delete one batch in the caller's transaction; returns how many rows went."""
    table, query = TARGETS[name]
    lock_planning_mutation(session)
    return len(
        session.execute(
            text(f"DELETE FROM {table} WHERE id IN ({query}) RETURNING id"),
            {"cutoff": cutoff, "batch": batch},
        ).all()
    )


def purge(
    session_factory,
    *,
    now: datetime,
    preview_retention: timedelta,
    notification_retention: timedelta | None,
    batch: int = BATCH_SIZE,
) -> dict[str, int]:
    """Delete everything past retention, one short transaction per batch."""
    deleted = dict.fromkeys(TARGETS, 0)
    for name, cutoff in _cutoffs(now, preview_retention, notification_retention).items():
        while True:
            with session_factory() as session, session.begin():
                removed = purge_batch(session, name, cutoff, batch)
            deleted[name] += removed
            if removed < batch:
                break
    return deleted


def run_cleanup(
    engine,
    *,
    now: datetime,
    preview_retention: timedelta,
    notification_retention: timedelta | None,
) -> dict[str, int] | None:
    """One cleanup pass, unless another process is running one; None when skipped."""
    with engine.connect() as guard:
        granted = guard.execute(
            text("SELECT pg_try_advisory_lock(:space, :key)"),
            {"space": CLEANUP_LOCK_KEY[0], "key": CLEANUP_LOCK_KEY[1]},
        ).scalar_one()
        guard.commit()
        if not granted:
            return None
        try:
            return purge(
                sessionmaker(bind=engine),
                now=now,
                preview_retention=preview_retention,
                notification_retention=notification_retention,
            )
        finally:
            guard.execute(
                text("SELECT pg_advisory_unlock(:space, :key)"),
                {"space": CLEANUP_LOCK_KEY[0], "key": CLEANUP_LOCK_KEY[1]},
            )
            guard.commit()

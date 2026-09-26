"""Run the retention pass on a timer inside the backend process."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from app.core import oplog
from app.modules.maintenance import retention

logger = logging.getLogger(__name__)


def retention_windows(settings) -> dict:
    return {
        "preview_retention": timedelta(hours=settings.preview_retention_hours),
        "notification_retention": timedelta(days=settings.notification_retention_days)
        if settings.notification_retention_days
        else None,
    }


async def run_periodically(engine, settings) -> None:
    """First pass after one interval, so a restart does not start with a burst of deletes."""
    interval = settings.retention_interval_minutes * 60
    while True:
        await asyncio.sleep(interval)
        try:
            with oplog.operation("maintenance.cleanup") as fields:
                deleted = await asyncio.to_thread(
                    retention.run_cleanup,
                    engine,
                    now=datetime.now(UTC),
                    **retention_windows(settings),
                )
                fields.update(skipped=deleted is None, deleted=deleted or {})
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Retention pass failed")

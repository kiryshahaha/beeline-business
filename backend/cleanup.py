"""Retention pass from the command line.

    python cleanup.py            # dry run: how many rows each rule would delete
    python cleanup.py --apply    # delete them

Rules and what is kept forever: app/modules/maintenance/README.md.
"""

import argparse
import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_engine
from app.modules.maintenance import retention
from app.modules.maintenance.periodic import retention_windows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="delete instead of counting")
    args = parser.parse_args()
    settings = get_settings()
    engine = get_engine()
    now = datetime.now(UTC)
    windows = retention_windows(settings)
    if args.apply:
        deleted = retention.run_cleanup(engine, now=now, **windows)
        result = {"mode": "apply", "skipped": deleted is None, "deleted": deleted or {}}
    else:
        with Session(engine) as session, session.begin():
            result = {
                "mode": "dry_run",
                "would_delete": retention.count_candidates(session, now=now, **windows),
            }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

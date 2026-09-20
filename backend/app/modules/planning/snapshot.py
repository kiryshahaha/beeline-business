"""Canonical snapshots include relations; a ticket timestamp alone cannot detect staleness."""

import hashlib
import json
from datetime import UTC, datetime

from app.modules.data_exchange.formats import json_default


def normalize(value):
    def encode(item):
        if isinstance(item, datetime):
            return item.astimezone(UTC).isoformat()
        return json_default(item)

    return json.loads(json.dumps(value, default=encode, sort_keys=True, allow_nan=False))


def fingerprint(snapshot: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            normalize(snapshot),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()

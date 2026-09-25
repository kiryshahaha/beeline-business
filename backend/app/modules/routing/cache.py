"""Process-local bounded cache for validated provider response payloads."""

import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock


@dataclass(frozen=True, slots=True)
class CacheEntry:
    payload: bytes
    source: str
    expires_at: datetime
    expires_at_monotonic: float


class GeoapifyResultCache:
    """LRU cache bounded by both entry count and serialized response bytes."""

    def __init__(
        self,
        *,
        max_entries: int = 256,
        max_bytes: int = 16 * 1024 * 1024,
        monotonic: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if max_entries < 1 or max_bytes < 1:
            raise ValueError("Cache bounds must be positive")
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._monotonic = monotonic
        self._utc_now = utc_now
        self._entries: OrderedDict[str, tuple[CacheEntry, int]] = OrderedDict()
        self._payload_bytes = 0
        self._lock = RLock()

    def get(self, key: str) -> CacheEntry | None:
        with self._lock:
            entry_with_size = self._entries.get(key)
            if entry_with_size is None:
                return None
            entry, _ = entry_with_size
            if entry.expires_at_monotonic <= self._monotonic():
                self._remove(key)
                return None
            self._entries.move_to_end(key)
            return entry

    def put(self, key: str, payload: bytes, source: str, ttl_seconds: float) -> bool:
        encoded = bytes(payload)
        if not key or not source or ttl_seconds <= 0 or len(encoded) > self._max_bytes:
            return False

        monotonic_now = self._monotonic()
        utc_now = self._utc_now()
        entry = CacheEntry(
            payload=encoded,
            source=source,
            expires_at=utc_now + timedelta(seconds=ttl_seconds),
            expires_at_monotonic=monotonic_now + ttl_seconds,
        )
        size = len(encoded)
        with self._lock:
            self._remove(key)
            while self._entries and (
                len(self._entries) >= self._max_entries
                or self._payload_bytes + size > self._max_bytes
            ):
                oldest = next(iter(self._entries))
                self._remove(oldest)
            self._entries[key] = (entry, size)
            self._payload_bytes += size
        return True

    def _remove(self, key: str) -> None:
        removed = self._entries.pop(key, None)
        if removed is not None:
            self._payload_bytes -= removed[1]


GEOAPIFY_RESULT_CACHE = GeoapifyResultCache()

"""Per-preview counters for routing-provider calls and calculation stages."""

import re
from collections import Counter
from threading import RLock

_SAFE_REASON = re.compile(r"^[a-z0-9_]{1,64}$")


class RoutingTelemetry:
    def __init__(self) -> None:
        self._provider_requests: Counter[str] = Counter()
        self._matrix_cells = 0
        self._cache_hits: Counter[str] = Counter()
        self._profiles: Counter[str] = Counter()
        self._stages: dict[str, dict[str, float | int]] = {}
        self._retry_attempts = 0
        self._estimation_sources: Counter[str] = Counter()
        self._error_reasons: Counter[str] = Counter()
        self._lock = RLock()

    def record_operation(self, stage: str, profile: str, *, cells: int, source: str) -> None:
        with self._lock:
            self._profiles[profile] += 1
            self._matrix_cells += cells
            self._estimation_sources[source] += 1

    def record_provider_request(self, stage: str) -> None:
        with self._lock:
            self._provider_requests[stage] += 1

    def record_cache_hit(self, stage: str) -> None:
        with self._lock:
            self._cache_hits[stage] += 1

    def record_retry(self) -> None:
        with self._lock:
            self._retry_attempts += 1

    def record_stage(self, stage: str, elapsed_seconds: float) -> None:
        with self._lock:
            metrics = self._stages.setdefault(stage, {"calls": 0, "duration_ms": 0.0})
            metrics["calls"] = int(metrics["calls"]) + 1
            metrics["duration_ms"] = float(metrics["duration_ms"]) + max(0, elapsed_seconds * 1000)

    def record_error(self, reason: str) -> None:
        safe_reason = reason if _SAFE_REASON.fullmatch(reason) else "routing_unknown_error"
        with self._lock:
            self._error_reasons[safe_reason] += 1

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "provider_requests": dict(sorted(self._provider_requests.items())),
                "matrix_cells": self._matrix_cells,
                "stages": {
                    name: {
                        "calls": values["calls"],
                        "duration_ms": round(float(values["duration_ms"]), 2),
                    }
                    for name, values in sorted(self._stages.items())
                },
                "cache_hits": dict(sorted(self._cache_hits.items())),
                "profiles": dict(sorted(self._profiles.items())),
                "retry_attempts": self._retry_attempts,
                "estimation_sources": dict(sorted(self._estimation_sources.items())),
                "error_reasons": dict(sorted(self._error_reasons.items())),
            }

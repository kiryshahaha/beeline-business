"""The one rule for which service area a ticket or an engineer belongs to.

A service area (участок) is the only hard territorial boundary; a city, district or
office name never decides it. Every source that states an area is a signal. They must
agree, and an unknown area is never replaced by the area of the current request.
"""

from collections.abc import Mapping

MISSING = "service_area_missing"
MISMATCH = "service_area_configuration_mismatch"


class ServiceAreaResolutionError(Exception):
    def __init__(self, code: str, subject: str, subject_id, sources: dict[str, int] | None = None):
        self.code = code
        self.subject = subject
        self.subject_id = subject_id
        self.sources = sources or {}
        super().__init__(code)

    def details(self) -> dict:
        return {
            "code": self.code,
            "subject": self.subject,
            "subject_id": self.subject_id,
            "sources": self.sources,
        }


def resolve_area(subject: str, subject_id, signals: Mapping[str, int | None]) -> int:
    """Return the single area all known signals agree on.

    No signal: `service_area_missing`. Two different areas: `service_area_configuration_mismatch`
    with every source, so the data can be fixed instead of one value silently winning.
    """
    known = {name: value for name, value in signals.items() if value is not None}
    if not known:
        raise ServiceAreaResolutionError(MISSING, subject, subject_id)
    if len(set(known.values())) > 1:
        raise ServiceAreaResolutionError(MISMATCH, subject, subject_id, dict(sorted(known.items())))
    return next(iter(known.values()))


def worker_signals(
    own: int | None,
    brigade: int | None = None,
    brigade_office: int | None = None,
    stock_office: int | None = None,
) -> dict[str, int | None]:
    """Worker profile, brigade division, the brigade's office and the stock office."""
    return {
        "worker": own,
        "brigade": brigade,
        "brigade_office": brigade_office,
        "stock_office": stock_office,
    }

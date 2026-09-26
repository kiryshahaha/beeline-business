"""One Moscow day boundary for every read model.

The planner, the warehouse and the schedule all treat a working day as the Moscow
calendar day, so the analytics, the feed and the calendar must use the same one. A
period is always the half-open interval `[start, end)`: a visit that ends exactly at
midnight belongs to the day that is closing, and nothing is counted twice. The
PostgreSQL session timezone is deliberately not consulted — a server running in UTC
would otherwise shift every day boundary by three hours.
"""

from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum

# Moscow has no daylight saving time, so a fixed offset is exact.
MOSCOW = timezone(timedelta(hours=3))


class Period(StrEnum):
    TODAY = "today"
    WEEK = "week"
    MONTH = "month"


def now() -> datetime:
    return datetime.now(MOSCOW)


def today() -> date:
    return now().date()


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """Moscow midnight of `day` and of the next day; the end is not included."""
    start = datetime.combine(day, time(0), MOSCOW)
    return start, start + timedelta(days=1)


def month_start(day: date) -> date:
    return day.replace(day=1)


def next_month_start(day: date) -> date:
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1)


def period_bounds(period: Period, at: datetime | None = None) -> tuple[datetime, datetime]:
    """Half-open Moscow interval of a calendar period containing `at`."""
    local = (at or now()).astimezone(MOSCOW)
    day = local.date()
    if period is Period.TODAY:
        return day_bounds(day)
    if period is Period.WEEK:
        monday = day - timedelta(days=day.weekday())
        start, _ = day_bounds(monday)
        return start, start + timedelta(days=7)
    start, _ = day_bounds(month_start(day))
    end, _ = day_bounds(next_month_start(day))
    return start, end

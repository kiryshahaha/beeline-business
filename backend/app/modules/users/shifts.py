"""Calculate worker working shift intervals for a given calendar date."""

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta

from app.core.workday import MOSCOW
from app.modules.schedule.schemas import ShiftInterval
from app.modules.users.enums import ScheduleType


def is_worker_working_on_date(
    target_date: date,
    schedule_type: ScheduleType | str = ScheduleType.FIVE_TWO,
    cycle_start_date: date | None = None,
    workdays_mask: Sequence[int] | int | None = None,
    is_exception: bool | None = None,
) -> bool:
    """Determine if the worker is scheduled to work on target_date.

    - If an explicit exception is present for target_date, its boolean status is used.
    - For 2/2 schedule: checks 4-day cycle from cycle_start_date: days 0, 1 are working, 2, 3 off.
    - For 5/2 schedule: checks weekday against workdays_mask (defaults to Mon-Fri: 0..4).
    """
    if is_exception is not None:
        return bool(is_exception)

    sched = ScheduleType(schedule_type) if isinstance(schedule_type, str) else schedule_type
    if sched == ScheduleType.TWO_TWO:
        if cycle_start_date is None:
            return True
        delta_days = (target_date - cycle_start_date).days
        return (delta_days % 4) in (0, 1)

    # 5/2 schedule
    weekday = target_date.weekday()
    if isinstance(workdays_mask, int):
        return bool(workdays_mask & (1 << weekday))
    if workdays_mask is not None:
        return weekday in workdays_mask
    return weekday in (0, 1, 2, 3, 4)


def get_shift_for_worker(
    worker: object,
    target_date: date,
    exceptions: Sequence[object] | None = None,
) -> ShiftInterval | None:
    """Extract worker fields and compute ShiftInterval for target_date."""

    def _get(obj, key, default=None):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    start_val = _get(worker, "workshift_start")
    if isinstance(start_val, str):
        start_time = time.fromisoformat(start_val)
    elif isinstance(start_val, time):
        start_time = start_val
    else:
        start_time = time(9)

    end_val = _get(worker, "workshift_end")
    if isinstance(end_val, str):
        end_time = time.fromisoformat(end_val)
    elif isinstance(end_val, time):
        end_time = end_val
    else:
        end_time = time(18)

    schedule_type = _get(worker, "schedule_type") or ScheduleType.FIVE_TWO
    cycle_start = _get(worker, "cycle_start_date")
    if isinstance(cycle_start, str):
        cycle_start = date.fromisoformat(cycle_start)
    mask = _get(worker, "workdays_mask", 31)

    exc_is_working = None
    exc_start = None
    exc_end = None
    if exceptions:
        for exc in exceptions:
            exc_date = _get(exc, "exception_date")
            if isinstance(exc_date, str):
                exc_date = date.fromisoformat(exc_date)
            if exc_date == target_date:
                exc_is_working = _get(exc, "is_working")
                s = _get(exc, "custom_workshift_start")
                e = _get(exc, "custom_workshift_end")
                exc_start = time.fromisoformat(s) if isinstance(s, str) else s
                exc_end = time.fromisoformat(e) if isinstance(e, str) else e
                break

    return get_worker_shift(
        target_date=target_date,
        workshift_start=start_time,
        workshift_end=end_time,
        schedule_type=schedule_type,
        cycle_start_date=cycle_start,
        workdays_mask=mask,
        exception_is_working=exc_is_working,
        exception_start=exc_start,
        exception_end=exc_end,
    )


def get_worker_shift(
    target_date: date | object,
    workshift_start: time | date | None = None,
    workshift_end: time | None = None,
    schedule_type: ScheduleType | str = ScheduleType.FIVE_TWO,
    cycle_start_date: date | None = None,
    workdays_mask: Sequence[int] | int | None = None,
    exception_is_working: bool | None = None,
    exception_start: time | None = None,
    exception_end: time | None = None,
    *,
    exceptions: Sequence[object] | None = None,
) -> ShiftInterval | None:
    """Return Moscow ShiftInterval or None if day off.

    Supports both:
    1) get_worker_shift(target_date, workshift_start, workshift_end, ...)
    2) get_worker_shift(worker, target_date, exceptions=...)
    """
    if not isinstance(target_date, date):
        # Case 2: worker object/dict as first parameter, target_date as second
        the_date = (
            workshift_start
            if isinstance(workshift_start, date)
            else date.fromisoformat(str(workshift_start))
        )
        return get_shift_for_worker(
            worker=target_date,
            target_date=the_date,
            exceptions=exceptions,
        )

    if workshift_start is None or workshift_end is None:
        raise ValueError("workshift_start and workshift_end are required when passing date first")

    if not is_worker_working_on_date(
        target_date=target_date,
        schedule_type=schedule_type,
        cycle_start_date=cycle_start_date,
        workdays_mask=workdays_mask,
        is_exception=exception_is_working,
    ):
        return None

    start_time = (
        exception_start
        if (exception_is_working and exception_start is not None)
        else workshift_start
    )
    end_time = (
        exception_end if (exception_is_working and exception_end is not None) else workshift_end
    )

    start_dt = datetime.combine(target_date, start_time, MOSCOW)
    end_dt = datetime.combine(target_date, end_time, MOSCOW)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)

    return ShiftInterval(start=start_dt, end=end_dt)

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo


def shift_covers_instant(
    *,
    kind: str,
    weekday: int | None,
    starts_on: date | None,
    ends_on: date | None,
    start_time: time | None,
    end_time: time | None,
    starts_at: datetime | None,
    ends_at: datetime | None,
    at: datetime,
    timezone: str,
) -> bool:
    """Evaluate recurring and explicit shifts using the complex's local calendar."""
    if at.tzinfo is None:
        at = at.replace(tzinfo=ZoneInfo(timezone))
    else:
        at = at.astimezone(ZoneInfo(timezone))

    if kind in {"ONE_TIME", "REPLACEMENT"}:
        if starts_at is None or ends_at is None:
            return False
        start_utc = starts_at.astimezone(at.tzinfo) if starts_at.tzinfo else starts_at.replace(tzinfo=dt_timezone.utc).astimezone(at.tzinfo)
        end_utc = ends_at.astimezone(at.tzinfo) if ends_at.tzinfo else ends_at.replace(tzinfo=dt_timezone.utc).astimezone(at.tzinfo)
        return start_utc <= at < end_utc

    if kind != "RECURRING" or weekday is None or start_time is None or end_time is None:
        return False

    local_day = at.date()
    # Looking at yesterday is required for shifts whose end time crosses midnight.
    for start_day in (local_day - timedelta(days=1), local_day):
        if start_day.weekday() != weekday:
            continue
        if starts_on is not None and start_day < starts_on:
            continue
        if ends_on is not None and start_day > ends_on:
            continue
        end_day = start_day + timedelta(days=1) if end_time <= start_time else start_day
        start_dt = datetime.combine(start_day, start_time, at.tzinfo)
        end_dt = datetime.combine(end_day, end_time, at.tzinfo)
        if start_dt <= at < end_dt:
            return True
    return False

"""ISO-8601 timestamps and local calendar dates.

The time-zone database is pinned to the ``tzdata`` package (not the host OS)
so that every machine resolves offsets identically.
"""
from __future__ import annotations

import zoneinfo
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache

zoneinfo.reset_tzpath(to=())  # force the pinned tzdata package


@lru_cache(maxsize=64)
def zone(name: str) -> zoneinfo.ZoneInfo:
    """Return a cached ZoneInfo for ``name``."""
    return zoneinfo.ZoneInfo(name)


def parse_ts(text: str) -> datetime:
    """Parse an ISO-8601 timestamp that must carry an explicit UTC offset."""
    if not isinstance(text, str):
        raise ValueError("timestamp must be a string")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError("timestamp without offset")
    return dt


def local_date(text: str, tz_name: str) -> date:
    """Return the calendar date of ``text`` in the time zone ``tz_name``."""
    return parse_ts(text).astimezone(zone(tz_name)).date()


def utc_date(text: str) -> date:
    """Return the UTC calendar date of a timestamp."""
    return parse_ts(text).astimezone(timezone.utc).date()


def parse_date(text: str) -> date:
    """Parse YYYY-MM-DD."""
    return date.fromisoformat(text)


def in_period(day: date, start: date, end: date) -> bool:
    """True when ``start <= day <= end``."""
    return start <= day <= end


def make_local(day: date, hour: int, minute: int, tz_name: str) -> datetime:
    """Build a normalised aware datetime for a local wall-clock time."""
    naive = datetime.combine(day, time(hour, minute))
    aware = naive.replace(tzinfo=zone(tz_name))
    return aware.astimezone(timezone.utc).astimezone(zone(tz_name))


def render_ts(moment: datetime, utc: bool) -> str:
    """Render a moment either in its own local offset or in +00:00."""
    target = moment.astimezone(timezone.utc) if utc else moment
    fixed = target.astimezone(timezone(target.utcoffset() or timedelta(0)))
    return fixed.isoformat(timespec="seconds")


def offset_minutes(moment: datetime) -> int:
    """Return the UTC offset of an aware datetime in minutes."""
    off = moment.utcoffset() or timedelta(0)
    return int(off.total_seconds() // 60)


def days_in_month(year: int, month: int) -> int:
    """Number of days in a month."""
    nxt = date(year + (month // 12), month % 12 + 1, 1)
    return (nxt - date(year, month, 1)).days

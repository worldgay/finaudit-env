"""Временные метки ISO-8601 и местные календарные даты.

База часовых поясов зафиксирована пакетом ``tzdata`` (а не ОС хоста),
поэтому любая машина вычисляет смещения одинаково.
"""
from __future__ import annotations

import zoneinfo
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache

zoneinfo.reset_tzpath(to=())  # принудительно используем зафиксированный пакет tzdata


@lru_cache(maxsize=64)
def zone(name: str) -> zoneinfo.ZoneInfo:
    """Возвращает кэшированный ZoneInfo для ``name``."""
    return zoneinfo.ZoneInfo(name)


def parse_ts(text: str) -> datetime:
    """Разбирает временную метку ISO-8601, обязанную иметь явное смещение UTC."""
    if not isinstance(text, str):
        raise ValueError("timestamp must be a string")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError("timestamp without offset")
    return dt


def local_date(text: str, tz_name: str) -> date:
    """Возвращает календарную дату ``text`` в часовом поясе ``tz_name``."""
    return parse_ts(text).astimezone(zone(tz_name)).date()


def utc_date(text: str) -> date:
    """Возвращает календарную дату временной метки по UTC."""
    return parse_ts(text).astimezone(timezone.utc).date()


def parse_date(text: str) -> date:
    """Разбирает YYYY-MM-DD."""
    return date.fromisoformat(text)


def in_period(day: date, start: date, end: date) -> bool:
    """True, если ``start <= day <= end``."""
    return start <= day <= end


def make_local(day: date, hour: int, minute: int, tz_name: str) -> datetime:
    """Строит нормализованный aware datetime для местного времени."""
    naive = datetime.combine(day, time(hour, minute))
    aware = naive.replace(tzinfo=zone(tz_name))
    return aware.astimezone(timezone.utc).astimezone(zone(tz_name))


def render_ts(moment: datetime, utc: bool) -> str:
    """Рендерит момент либо в его местном смещении, либо в +00:00."""
    target = moment.astimezone(timezone.utc) if utc else moment
    fixed = target.astimezone(timezone(target.utcoffset() or timedelta(0)))
    return fixed.isoformat(timespec="seconds")


def offset_minutes(moment: datetime) -> int:
    """Возвращает смещение UTC aware datetime в минутах."""
    off = moment.utcoffset() or timedelta(0)
    return int(off.total_seconds() // 60)


def days_in_month(year: int, month: int) -> int:
    """Число дней в месяце."""
    nxt = date(year + (month // 12), month % 12 + 1, 1)
    return (nxt - date(year, month, 1)).days

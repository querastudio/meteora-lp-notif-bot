from __future__ import annotations

from datetime import datetime, timedelta, timezone


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_local(dt: datetime, utc_offset_hours: int) -> datetime:
    return dt.astimezone(timezone(timedelta(hours=utc_offset_hours)))


def format_local(dt: datetime, utc_offset_hours: int) -> str:
    local = to_local(dt, utc_offset_hours)
    return local.strftime("%Y-%m-%d %H:%M:%S") + f" (UTC+{utc_offset_hours})"

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def parse_datetime(value: str, timezone_name: str) -> datetime:
    if value.lower() == "now":
        return datetime.now(ZoneInfo(timezone_name))

    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed


def floor_window_end(value: datetime, window_minutes: int) -> datetime:
    local = value
    minute = (local.minute // window_minutes) * window_minutes
    return local.replace(minute=minute, second=0, microsecond=0)


def window_from_end(window_end: datetime, window_minutes: int) -> tuple[datetime, datetime]:
    end = floor_window_end(window_end, window_minutes)
    start = end - timedelta(minutes=window_minutes)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)

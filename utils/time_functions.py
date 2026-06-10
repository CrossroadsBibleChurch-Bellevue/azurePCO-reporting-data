from typing import Optional
from zoneinfo import ZoneInfo
from datetime import datetime, timezone

def parse_iso(dt_str: Optional[str]) -> Optional[datetime]:
    if not dt_str:
        return None
    s = dt_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def to_local(dt: Optional[datetime], tz: ZoneInfo) -> Optional[datetime]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def iso_local(dt_str: Optional[str], tz: ZoneInfo) -> Optional[str]:
    dt = to_local(parse_iso(dt_str), tz)
    return dt.isoformat() if dt else None
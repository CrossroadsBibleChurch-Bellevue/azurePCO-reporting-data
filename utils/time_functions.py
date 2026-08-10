from typing import Optional, Any
from zoneinfo import ZoneInfo
from datetime import datetime, timezone

from utils.env_fetcher import timezone_env

LOCAL_TIMEZONE, SQL_DATETIME_FORMAT = timezone_env()

SQL_DATETIME_FIELD_NAMES = {
    "generated_at",
    "archived_at",
    "created_at",
    "updated_at",
    "joined_at",
    "left_at",
    "starts_at",
    "ends_at",
    "canceled_at",
    "published_at",
    "last_joined_at",
    "reminders_sent_at",
    "first_instance_starts_at",
    "last_instance_starts_at",
}

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

def parse_pco_datetime(value: Optional[str]):
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError:
        return None

    # Original API timestamps include a UTC offset. Converted SQL output
    # strings do not, so interpret naive values as Los Angeles local time.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TIMEZONE)

    return parsed
    

def to_local_sql_datetime(value: Optional[Any]):
    """
    Convert a datetime or ISO 8601 datetime string to America/Los_Angeles
    local time and return a SQL Server datetime-compatible string.

    Output format:
        YYYY-MM-DD HH:MM:SS.mmm

    Returns None when the input is None, empty, or cannot be parsed.
    """

    if value is None or value == "":
        return None

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except ValueError:
            return None
    else:
        return None

    # Planning Center timestamps should contain an offset. If a naive
    # datetime is encountered, treat it as UTC rather than interpreting
    # it using the host computer's local time zone.
    #if parsed.tzinfo is None:
    #    parsed = parsed.replace(tzinfo=timezone.utc)

    local_datetime = parsed.astimezone(LOCAL_TIMEZONE)

    # SQL Server datetime uses millisecond-level precision.
    return local_datetime.strftime(SQL_DATETIME_FORMAT)[:-3]

def convert_output_datetimes_to_local_sql(value: Any) -> Any:
    """
    Recursively convert known datetime fields in an output object to
    America/Los_Angeles local time using a SQL datetime-compatible format.

    This mutates dictionaries and lists in place and also returns them.
    """

    if isinstance(value, dict):
        for key, item in value.items():
            if key in SQL_DATETIME_FIELD_NAMES:
                value[key] = to_local_sql_datetime(item)
            else:
                value[key] = convert_output_datetimes_to_local_sql(item)

        return value

    if isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = convert_output_datetimes_to_local_sql(item)

        return value

    return value

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def format_api_datetime(value: datetime) -> str:
    """
    Format a timezone-aware datetime for PCO query parameters.

    Example:
        2026-08-01T19:51:51Z
    """
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
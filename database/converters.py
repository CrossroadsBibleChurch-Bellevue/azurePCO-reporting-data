from datetime import datetime, timezone
from typing import Any, Optional


NULL_STRINGS = {
    "",
    "none",
    "null",
    "nan",
    "n/a",
    "undefined",
}


def normalize_optional_datetime(value: Any):
    if value is None:
        return None

    if isinstance(value, datetime):
        parsed_value = value

    elif isinstance(value, str):
        cleaned_value = value.strip()

        if cleaned_value.lower() in NULL_STRINGS:
            return None

        try:
            parsed_value = datetime.fromisoformat(
                cleaned_value.replace("Z", "+00:00")
            )

        except ValueError as error:
            raise ValueError(
                f"Invalid datetime value: {value!r}"
            ) from error

    else:
        raise TypeError(
            f"Expected datetime, string, or None, but received "
            f"{type(value).__name__}: {value!r}"
        )

    if parsed_value.tzinfo is not None:
        parsed_value = (
            parsed_value
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )

    return parsed_value
from dataclasses import dataclass
from datetime import datetime, date, timezone
from pathlib import Path
import requests
from urllib.parse import urljoin
import time
from typing import Any
from dateutil.parser import isoparse
import re
import os

from datetime import datetime, date, timezone
# This just contains some functions that were needed by both checkins full and delta and didn't know where else to put it, so put them here


BASE_URL = "https://api.planningcenteronline.com/check-ins/v2/"
DEFAULT_PER_PAGE = 100
REQUEST_TIMEOUT_SECONDS = 45
MAX_RETRIES = 5


class PCOError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    app_id: str
    secret: str
    event_id: str | None
    start_date: date | None
    end_date: date | None
    checkin_updated_since: datetime
    event_time_updated_since: datetime
    output_dir: Path
    output_prefix: str
    max_events: int | None
    max_workers: int


class PCOClient:
    def __init__(self, app_id: str, secret: str) -> None:
        self.session = requests.Session()
        self.session.auth = (app_id, secret)
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "pco-checkins-tester/1.0",
            }
        )

    def get_json(self, path_or_url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = path_or_url if path_or_url.startswith("http") else urljoin(BASE_URL, path_or_url.lstrip("/"))

        for attempt in range(1, MAX_RETRIES + 1):
            response = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                sleep_seconds = int(retry_after) if retry_after and retry_after.isdigit() else min(2 ** attempt, 30)
                time.sleep(sleep_seconds)
                continue

            if 500 <= response.status_code < 600 and attempt < MAX_RETRIES:
                time.sleep(min(2 ** attempt, 30))
                continue

            if not response.ok:
                body = response.text[:2000]
                raise PCOError(f"GET {response.url} failed: {response.status_code} {response.reason}\n{body}")

            try:
                return response.json()
            except ValueError as exc:
                raise PCOError(f"GET {response.url} returned invalid JSON") from exc

        raise PCOError(f"GET {url} failed after {MAX_RETRIES} attempts")

    def paginate(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        params = dict(params or {})
        params.setdefault("per_page", DEFAULT_PER_PAGE)

        output: list[dict[str, Any]] = []
        next_url: str | None = path

        while next_url:
            payload = self.get_json(next_url, params=params if not next_url.startswith("http") else None)

            data = payload.get("data", [])
            if isinstance(data, dict):
                output.append(data)
            elif isinstance(data, list):
                output.extend(data)
            else:
                raise PCOError(f"Unexpected JSON:API data shape for {next_url}")

            included = payload.get("included") or []
            if included:
                output.extend(included)

            links = payload.get("links") or {}
            next_url = links.get("next")
            params = None

        return output

    def paginate_updated_since(
        self,
        path: str,
        updated_since: datetime,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        params = dict(params or {})
        params.setdefault("per_page", DEFAULT_PER_PAGE)
        params["order"] = "-updated_at"

        output: list[dict[str, Any]] = []
        next_url: str | None = path

        while next_url:
            payload = self.get_json(
                next_url,
                params=params if not next_url.startswith("http") else None,
            )

            data = payload.get("data", [])

            if isinstance(data, dict):
                page_resources = [data]
            elif isinstance(data, list):
                page_resources = data
            else:
                raise PCOError(
                    f"Unexpected JSON:API data shape for {next_url}"
                )

            retained_ids: set[str] = set()
            reached_cutoff = False

            for resource in page_resources:
                updated_at_raw = attrs(resource).get("updated_at")
                updated_at = parse_dt(updated_at_raw)

                if updated_at is None:
                    raise PCOError(
                        f"Resource {resource.get('type')}:{resource.get('id')} "
                        f"has a missing or invalid updated_at: {updated_at_raw}"
                    )

                if updated_at < updated_since:
                    reached_cutoff = True
                    break

                output.append(resource)
                retained_ids.add(str(resource.get("id")))

            included = payload.get("included") or []

            if retained_ids:
                output.extend(included)

            if reached_cutoff:
                break

            links = payload.get("links") or {}
            next_url = links.get("next")
            params = None

        return output

    def get_collection_payloads(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """
        Like paginate(), but preserves each JSON:API resource exactly and includes included resources
        in the same returned list. Used for indexing heterogeneous resource types.
        """
        return self.paginate(path, params)

def attrs(resource: dict[str, Any] | None) -> dict[str, Any]:
    if not resource:
        return {}
    return resource.get("attributes") or {}

def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = isoparse(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None

def rel_id(resource: dict[str, Any] | None, relationship_name: str) -> str | None:
    if not resource:
        return None
    rel = (resource.get("relationships") or {}).get(relationship_name) or {}
    data = rel.get("data")
    if isinstance(data, dict):
        return str(data.get("id")) if data.get("id") is not None else None
    return None

def resource_date(resource: dict[str, Any], *field_names: str) -> date | None:
    a = attrs(resource)
    for field_name in field_names:
        dt = parse_dt(a.get(field_name))
        if dt:
            return dt.date()
    return None


def date_in_range(value: date | None, start: date | None, end: date | None) -> bool:
    if value is None:
        return True
    if start and value < start:
        return False
    if end and value > end:
        return False
    return True



def safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0

def getenv_blank_as_none(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None

def parse_bool_env(name: str, default: bool = False) -> bool:
    value = getenv_blank_as_none(name)

    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "y", "on"}

def parse_date_env(name: str) -> date | None:
    value = getenv_blank_as_none(name)
    if not value:
        return None
    try:
        return isoparse(value).date()
    except Exception as exc:
        raise ValueError(f"{name} must be ISO date/datetime. Got: {value}") from exc


def parse_datetime_env(value: str) -> datetime:
    if not value:
        raise ValueError("Missing required datetime value")

    value = value.strip()

    # Python datetime supports microseconds: at most 6 fractional digits.
    # Example: .8387577 becomes .838757
    value = re.sub(
        r"(\.\d{6})\d+",
        r"\1",
        value,
    )

    try:
        parsed = isoparse(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Must be a valid ISO datetime. Got: {value!r}"
        ) from exc

    # Treat timezone-less SQL datetime2 values as UTC.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)
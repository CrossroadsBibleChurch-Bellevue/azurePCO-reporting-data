#!/usr/bin/env python3

import argparse
import os
import sys
import time
from dotenv import load_dotenv
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin

import requests

load_dotenv()

BASE_URL = "https://api.planningcenteronline.com/groups/v2/"
DEFAULT_PER_PAGE = 100
LOCAL_TIMEZONE_NAME = os.getenv("LOCAL_TIMEZONE")
LOCAL_TIMEZONE = ZoneInfo(LOCAL_TIMEZONE_NAME)
SQL_DATETIME_FORMAT = os.getenv("SQL_DATETIME_FORMAT")


class PCOApiError(RuntimeError):
    pass


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


def rel_id(resource: Dict[str, Any], relationship_name: str) -> Optional[str]:
    rel = resource.get("relationships", {}).get(relationship_name, {})
    data = rel.get("data")
    if isinstance(data, dict):
        return data.get("id")
    return None


def compact_person(person: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not person:
        return None

    attrs = person.get("attributes", {})
    return {
        "id": person.get("id"),
        "first_name": attrs.get("first_name"),
        "last_name": attrs.get("last_name"),
        "avatar_url": attrs.get("avatar_url"),
        "permissions": attrs.get("permissions"),
    }


def compact_group(group: Dict[str, Any]) -> Dict[str, Any]:
    attrs = group.get("attributes", {})
    return {
        "id": group.get("id"),
        "name": attrs.get("name"),
        "description": attrs.get("description_as_plain_text") or attrs.get("description"),
        "archived_at": attrs.get("archived_at"),
        "created_at": attrs.get("created_at"),
        "memberships_count": attrs.get("memberships_count"),
        "schedule": attrs.get("schedule"),
        "listed": attrs.get("listed"),
        "events_listed": attrs.get("events_listed"),
        "events_visibility": attrs.get("events_visibility"),
        "location_type_preference": attrs.get("location_type_preference"),
        "virtual_location_url": attrs.get("virtual_location_url"),
        "public_church_center_web_url": attrs.get("public_church_center_web_url"),
        "group_type_id": rel_id(group, "group_type"),
        "location_id": rel_id(group, "location"),
    }


def compact_group_type(group_type: Dict[str, Any]) -> Dict[str, Any]:
    attrs = group_type.get("attributes", {})

    return {
        "id": group_type.get("id"),
        "name": attrs.get("name"),
        "church_center_visible": attrs.get("church_center_visible"),
    }

def compact_membership(
    membership: Dict[str, Any],
    included_people_by_id: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    attrs = membership.get("attributes", {})
    person_id = rel_id(membership, "person")

    return {
        "id": membership.get("id"),
        "group_id": rel_id(membership, "group"),
        "person_id": person_id,
        "role": attrs.get("role"),
        "joined_at": attrs.get("joined_at"),
        "left_at": attrs.get("left_at"),
        "person": compact_person(
            included_people_by_id.get(person_id)
        ),
    }


def compact_event(event: Dict[str, Any]) -> Dict[str, Any]:
    attrs = event.get("attributes", {})

    return {
        "id": event.get("id"),
        "group_id": rel_id(event, "group"),
        "parent_event_id": rel_id(event, "repeating_event") or event.get("id"),
        "repeating_event_id": rel_id(event, "repeating_event"),
        "name": attrs.get("name"),
        "description": attrs.get("description"),
        "starts_at": attrs.get("starts_at"),
        "ends_at": attrs.get("ends_at"),
        "canceled": attrs.get("canceled"),
        "canceled_at": attrs.get("canceled_at"),
        "multi_day": attrs.get("multi_day"),
        "repeating": attrs.get("repeating"),
        "location_type_preference": attrs.get("location_type_preference"),
        "virtual_location_url": attrs.get("virtual_location_url"),
        "visitors_count": attrs.get("visitors_count"),
        "attendance_requests_enabled": attrs.get(
            "attendance_requests_enabled"
        ),
        "automated_reminder_enabled": attrs.get(
            "automated_reminder_enabled"
        ),
        "reminders_sent": attrs.get("reminders_sent"),
        "reminders_sent_at": attrs.get("reminders_sent_at"),
        "attendance_submitter_id": rel_id(
            event,
            "attendance_submitter",
        ),
        "location_id": rel_id(event, "location"),
    }

def compact_tag_group(
    tag_group: Dict[str, Any],
) -> Dict[str, Any]:
    attrs = tag_group.get("attributes", {})

    return {
        "tag_group_id": tag_group.get("id"),
        "name": attrs.get("name"),
        "position": attrs.get("position"),
        "display_publicly": attrs.get("display_publicly"),
        "multiple_options_enabled": attrs.get(
            "multiple_options_enabled"
        ),
    }


def compact_tag(
    tag: Dict[str, Any],
    fallback_tag_group_id: Optional[str] = None,
) -> Dict[str, Any]:
    attrs = tag.get("attributes", {})

    return {
        "tag_id": tag.get("id"),
        "tag_group_id": (
            rel_id(tag, "tag_group")
            or fallback_tag_group_id
        ),
        "name": attrs.get("name"),
        "position": attrs.get("position"),
    }

def included_by_type_and_id(payload: Dict[str, Any]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    included = {}

    for item in payload.get("included", []) or []:
        item_type = item.get("type")
        item_id = item.get("id")

        if item_type and item_id:
            included[(item_type, item_id)] = item

    return included


class PlanningCenterClient:
    def __init__(
        self,
        app_id: str,
        secret: str,
        timeout: int = 60,
        max_retries: int = 4,
    ) -> None:
        self.session = requests.Session()
        self.session.auth = (app_id, secret)
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "pco-groups-tester/1.0",
            }
        )
        self.timeout = timeout
        self.max_retries = max_retries

    def get(self, path_or_url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = path_or_url if path_or_url.startswith("http") else urljoin(BASE_URL, path_or_url.lstrip("/"))

        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise PCOApiError(f"Request failed: {url} :: {exc}") from exc
                time.sleep(2 ** attempt)
                continue

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "2"))
                time.sleep(retry_after)
                continue

            if 500 <= response.status_code < 600:
                if attempt >= self.max_retries:
                    raise PCOApiError(f"Server error {response.status_code}: {url} :: {response.text[:500]}")
                time.sleep(2 ** attempt)
                continue

            if not response.ok:
                raise PCOApiError(f"HTTP {response.status_code}: {url} :: {response.text[:1000]}")

            try:
                return response.json()
            except ValueError as exc:
                raise PCOApiError(f"Invalid JSON response: {url}") from exc

        raise PCOApiError(f"Request failed after retries: {url}")

    def paginate(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        max_pages: Optional[int] = None,
    ) -> Iterable[Dict[str, Any]]:
        params = dict(params or {})
        params.setdefault("per_page", DEFAULT_PER_PAGE)

        next_url = path
        page_count = 0

        while next_url:
            page_count += 1

            if max_pages is not None and page_count > max_pages:
                break

            payload = self.get(next_url, params=params if page_count == 1 else None)

            yield payload

            next_url = payload.get("links", {}).get("next")

def fetch_group_types(
    client: PlanningCenterClient,
) -> List[Dict[str, Any]]:
    group_types = []

    for payload in client.paginate(
        "group_types",
        {
            "order": "name",
        },
    ):
        for group_type in payload.get("data", []):
            group_types.append(compact_group_type(group_type))

    return group_types

def fetch_groups(client: PlanningCenterClient, include_archived: bool) -> List[Dict[str, Any]]:
    groups = []

    for payload in client.paginate("groups", {"order": "name"}):
        for group in payload.get("data", []):
            compact = compact_group(group)

            if not include_archived and compact.get("archived_at"):
                continue

            groups.append(compact)

    return groups


def fetch_memberships_for_group(
    client: PlanningCenterClient,
    group_id: str,
) -> List[Dict[str, Any]]:
    memberships = []

    for payload in client.paginate(
        f"groups/{group_id}/memberships",
        {
            "include": "person",
            "order": "last_name",
        },
    ):
        included = included_by_type_and_id(payload)
        people_by_id = {
            item_id: item
            for (item_type, item_id), item in included.items()
            if item_type == "Person"
        }

        for membership in payload.get("data", []):
            memberships.append(compact_membership(membership, people_by_id))

    return memberships


def fetch_events(client: PlanningCenterClient, max_event_pages: Optional[int]) -> List[Dict[str, Any]]:
    events = []

    for payload in client.paginate(
        "events",
        {
            "include": "group",
            "order": "starts_at",
        },
        max_pages=max_event_pages,
    ):
        for event in payload.get("data", []):
            events.append(compact_event(event))

    return events

def fetch_tag_groups(
    client: PlanningCenterClient,
) -> List[Dict[str, Any]]:
    tag_groups = []

    for payload in client.paginate(
        "tag_groups",
        {
            "order": "position",
        },
    ):
        for tag_group in payload.get("data", []):
            tag_groups.append(compact_tag_group(tag_group))

    return tag_groups


def fetch_tags_for_tag_group(
    client: PlanningCenterClient,
    tag_group_id: str,
) -> List[Dict[str, Any]]:
    tags = []

    for payload in client.paginate(
        f"tag_groups/{tag_group_id}/tags",
        {
            "order": "position",
        },
    ):
        for tag in payload.get("data", []):
            tags.append(
                compact_tag(
                    tag,
                    fallback_tag_group_id=tag_group_id,
                )
            )

    return tags


def fetch_all_tags(
    client: PlanningCenterClient,
    tag_groups: List[Dict[str, Any]],
    workers: int,
) -> List[Dict[str, Any]]:
    tags_by_id: Dict[str, Dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(
                fetch_tags_for_tag_group,
                client,
                tag_group["tag_group_id"],
            ): tag_group["tag_group_id"]
            for tag_group in tag_groups
            if tag_group.get("tag_group_id")
        }

        for future in as_completed(future_map):
            tag_group_id = future_map[future]

            try:
                tag_group_tags = future.result()
            except Exception as exc:
                print(
                    "Tag fetch failed for "
                    f"tag_group_id={tag_group_id}: {exc}",
                    file=sys.stderr,
                )
                continue

            for tag in tag_group_tags:
                tag_id = tag.get("tag_id")

                if tag_id:
                    tags_by_id[tag_id] = tag

    return sorted(
        tags_by_id.values(),
        key=lambda tag: (
            tag.get("tag_group_id") or "",
            tag.get("position")
            if tag.get("position") is not None
            else sys.maxsize,
            tag.get("name") or "",
        ),
    )


def fetch_group_tags_for_group(
    client: PlanningCenterClient,
    group_id: str,
) -> List[Dict[str, Any]]:
    group_tags = []

    for payload in client.paginate(
        f"groups/{group_id}/tags",
        {
            "order": "position",
        },
    ):
        for tag in payload.get("data", []):
            group_tags.append(
                {
                    "group_id": group_id,
                    "tag_id": tag.get("id"),
                    "tag_group_id": rel_id(
                        tag,
                        "tag_group",
                    ),
                }
            )

    return group_tags


def fetch_group_tags(
    client: PlanningCenterClient,
    groups: List[Dict[str, Any]],
    workers: int,
) -> List[Dict[str, Any]]:
    group_tags = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(
                fetch_group_tags_for_group,
                client,
                group["id"],
            ): group["id"]
            for group in groups
            if group.get("id")
        }

        for future in as_completed(future_map):
            group_id = future_map[future]

            try:
                group_tags.extend(future.result())
            except Exception as exc:
                print(
                    "Group tag fetch failed for "
                    f"group_id={group_id}: {exc}",
                    file=sys.stderr,
                )

    return sorted(
        group_tags,
        key=lambda row: (
            row.get("group_id") or "",
            row.get("tag_group_id") or "",
            row.get("tag_id") or "",
        ),
    )

def classify_and_limit_events(
    events: List[Dict[str, Any]],
    mode: str,
    past_limit: Optional[int],
    future_limit: Optional[int],
) -> List[Dict[str, Any]]:
    """
    Classifies events as past/future based on ends_at when available, otherwise starts_at.
    Applies past/future limits per group.

    - past: events whose ends_at/starts_at is before now
    - future: events whose ends_at/starts_at is now or later
    - unknown datetime events are excluded because they cannot be classified safely
    """

    current_time = now_utc()

    events_by_group: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(
        lambda: {"past": [], "future": []}
    )

    for event in events:
        group_id = event.get("group_id")
        if not group_id:
            continue

        starts_at = parse_pco_datetime(event.get("starts_at"))
        ends_at = parse_pco_datetime(event.get("ends_at"))

        comparison_datetime = ends_at or starts_at

        if comparison_datetime is None:
            event["event_time_classification"] = "unknown"
            continue

        if comparison_datetime < current_time:
            event["event_time_classification"] = "past"
            events_by_group[group_id]["past"].append(event)
        else:
            event["event_time_classification"] = "future"
            events_by_group[group_id]["future"].append(event)

    selected_events: List[Dict[str, Any]] = []

    for group_events in events_by_group.values():
        past_events = sorted(
            group_events["past"],
            key=lambda event: (
                parse_pco_datetime(event.get("starts_at"))
                or datetime.min.replace(tzinfo=timezone.utc)
            ),
            reverse=True,
        )

        future_events = sorted(
            group_events["future"],
            key=lambda event: (
                parse_pco_datetime(event.get("starts_at"))
                or datetime.max.replace(tzinfo=timezone.utc)
            ),
        )

        if mode in ("past", "all"):
            selected_events.extend(
                past_events[:past_limit] if past_limit is not None else past_events
            )

        if mode in ("future", "all"):
            selected_events.extend(
                future_events[:future_limit] if future_limit is not None else future_events
            )

    return sorted(
        selected_events,
        key=lambda event: (
            event.get("group_id") or "",
            parse_pco_datetime(event.get("starts_at"))
            or datetime.max.replace(tzinfo=timezone.utc),
        ),
    )


def fetch_attendance_for_event(
    client: PlanningCenterClient,
    event_id: str,
) -> Dict[str, Any]:
    attendance_records = []

    for payload in client.paginate(
        f"events/{event_id}/attendances",
        {
            "include": "person",
            "order": "last_name",
        },
    ):
        included = included_by_type_and_id(payload)
        people_by_id = {
            item_id: item
            for (item_type, item_id), item in included.items()
            if item_type == "Person"
        }

        for attendance in payload.get("data", []):
            attrs = attendance.get("attributes", {})
            person_id = rel_id(attendance, "person")
            attended = attrs.get("attended") is True

            attendance_records.append(
                {
                    "id": attendance.get("id"),
                    "event_id": rel_id(attendance, "event") or event_id,
                    "person_id": person_id,
                    "attended": attended,
                    "role": attrs.get("role"),
                    "person": compact_person(people_by_id.get(person_id)),
                }
            )

    attended_records = [record for record in attendance_records if record["attended"]]
    absent_records = [record for record in attendance_records if not record["attended"]]

    total_recorded = len(attendance_records)
    attended_count = len(attended_records)

    return {
        "event_id": event_id,
        "attendance_record_count": total_recorded,
        "attended_count": attended_count,
        "absent_or_not_attended_count": len(absent_records),
        "attendance_rate": round(attended_count / total_recorded, 4) if total_recorded else None,
        "attended_members": attended_records,
        "not_attended_members": absent_records,
        "all_attendance_records": attendance_records,
    }


def fetch_attendance_for_events(
    client: PlanningCenterClient,
    events: List[Dict[str, Any]],
    workers: int,
) -> Dict[str, Dict[str, Any]]:
    if not events:
        return {}

    attendance_by_event = {}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(fetch_attendance_for_event, client, event["id"]): event["id"]
            for event in events
        }

        for future in as_completed(future_map):
            event_id = future_map[future]

            try:
                attendance_by_event[event_id] = future.result()
            except Exception as exc:
                attendance_by_event[event_id] = {
                    "event_id": event_id,
                    "error": str(exc),
                    "attendance_record_count": 0,
                    "attended_count": 0,
                    "absent_or_not_attended_count": 0,
                    "attendance_rate": None,
                    "attended_members": [],
                    "not_attended_members": [],
                    "all_attendance_records": [],
                }

    return attendance_by_event


def build_output(
    groups: List[Dict[str, Any]],
    group_types: List[Dict[str, Any]],
    memberships_by_group: Dict[str, List[Dict[str, Any]]],
    events: List[Dict[str, Any]],
    attendance_by_event: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    events_by_group = defaultdict(list)
    group_types_by_id = {
        group_type["id"]: group_type
        for group_type in group_types
        if group_type.get("id")
    }

    for event in events:
        attendance = attendance_by_event.get(event["id"], {})
        event["attendance"] = attendance
        events_by_group[event.get("group_id")].append(event)

    output_groups = []

    for group in groups:
        group_id = group["id"]
        group_type_id = group.get("group_type_id")
        group["group_type"] = group_types_by_id.get(group_type_id)
        memberships = memberships_by_group.get(group_id, [])
        group_events = events_by_group.get(group_id, [])

        event_attendance_rates = [
            event.get("attendance", {}).get("attendance_rate")
            for event in group_events
            if event.get("attendance", {}).get("attendance_rate") is not None
        ]

        group["memberships"] = memberships
        group["events"] = group_events
        group["analytics"] = {
            "membership_count_from_memberships_endpoint": len(memberships),
            "event_count_returned": len(group_events),
            "average_event_attendance_rate": (
                round(sum(event_attendance_rates) / len(event_attendance_rates), 4)
                if event_attendance_rates
                else None
            ),
            "total_attended_count_across_returned_events": sum(
                event.get("attendance", {}).get("attended_count", 0)
                for event in group_events
            ),
            "total_attendance_records_across_returned_events": sum(
                event.get("attendance", {}).get("attendance_record_count", 0)
                for event in group_events
            ),
        }

        output_groups.append(group)

    return {
        "generated_at": now_utc().isoformat(),
        "summary": {
            "group_type_count": len(group_types),
            "group_count": len(output_groups),
            "event_count": len(events),
            "attendance_event_count": len(attendance_by_event),
        },
        "group_types": group_types,
        "groups": output_groups,
    }

def truncate_value(value: Any, max_length: int = 40) -> str:
    if value is None:
        return ""

    text = str(value)

    if len(text) > max_length:
        return text[: max_length - 3] + "..."

    return text


def print_table(
    title: str,
    rows: List[Dict[str, Any]],
    columns: List[str],
    limit: Optional[int] = 10,
) -> None:
    print()
    print(title)
    print("-" * len(title))

    if not rows:
        print("No rows returned.")
        return

    preview_rows = rows if limit is None else rows[:limit]

    column_widths = {}

    for column in columns:
        header_width = len(column)
        value_width = max(
            len(truncate_value(row.get(column)))
            for row in preview_rows
        )
        column_widths[column] = max(header_width, value_width)

    header = " | ".join(
        column.ljust(column_widths[column])
        for column in columns
    )

    separator = "-+-".join(
        "-" * column_widths[column]
        for column in columns
    )

    print(header)
    print(separator)

    for row in preview_rows:
        print(
            " | ".join(
                truncate_value(row.get(column)).ljust(column_widths[column])
                for column in columns
            )
        )

    if limit is None:
        print(f"\nShowing all {len(rows)} rows.")
    else:
        print(f"\nShowing {min(limit, len(rows))} of {len(rows)} rows.")


def full_name(person: Optional[Dict[str, Any]]) -> str:
    if not person:
        return ""

    first_name = person.get("first_name") or ""
    last_name = person.get("last_name") or ""

    return f"{first_name} {last_name}".strip()


def build_group_types_table_rows(
    output: Dict[str, Any],
) -> List[Dict[str, Any]]:
    groups_per_type: Dict[str, int] = defaultdict(int)

    for group in output.get("groups", []):
        group_type_id = group.get("group_type_id")

        if group_type_id:
            groups_per_type[group_type_id] += 1

    rows = []

    for group_type in output.get("group_types", []):
        group_type_id = group_type.get("id")

        rows.append(
            {
                "group_type_id": group_type_id,
                "group_type_name": group_type.get("name"),
                "church_center_visible": group_type.get(
                    "church_center_visible"
                ),
                "group_count": groups_per_type.get(group_type_id, 0),
            }
        )

    return rows


def build_group_overview_table_rows(output: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []

    for group in output["groups"]:
        analytics = group.get("analytics", {})
        memberships = group.get("memberships", [])
        events = group.get("events", [])

        attended_total = analytics.get("total_attended_count_across_returned_events") or 0
        attendance_records_total = analytics.get("total_attendance_records_across_returned_events") or 0

        rows.append(
            {
                "group_id": group.get("id"),
                "group_name": group.get("name"),
                "group_type_id": group.get("group_type_id"),
                "member_count": len(memberships),
                "pco_memberships_count": group.get("memberships_count"),
                "event_count": len(events),
                "total_attended": attended_total,
                "total_attendance_records": attendance_records_total,
                "created_at": group.get("created_at"),
                "archived_at": group.get("archived_at"),
            }
        )

    return rows

def build_group_members_table_rows(output: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []

    for group in output["groups"]:
        group_id = group.get("id")
        group_name = group.get("name")
        group_type = group.get("group_type") or {}
        group_type_id = group.get("group_type_id")
        group_type_name = group_type.get("name")

        for membership in group.get("memberships", []):
            person = membership.get("person")

            rows.append(
                {
                    "group_id": group_id,
                    "group_name": group_name,
                    "group_type_id": group_type_id,
                    "membership_id": membership.get("id"),
                    "person_id": membership.get("person_id"),
                    "member_name": full_name(person),
                    "first_name": person.get("first_name") if person else "",
                    "last_name": person.get("last_name") if person else "",
                    "role": membership.get("role"),
                    "joined_at": membership.get("joined_at"),
                }
            )

    return rows

def build_group_memberships_table_rows(
    output: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Build one row per membership returned by Planning Center.

    Important:
    The Groups memberships endpoint normally represents current
    memberships. Former memberships that have been removed from Planning
    Center may no longer be returned by the API.
    """

    rows = []

    for group in output.get("groups", []):
        group_id = group.get("id")

        for membership in group.get("memberships", []):
            rows.append(
                {
                    "membership_id": membership.get("id"),
                    "group_id": group_id,
                    "person_id": membership.get("person_id"),
                    "joined_at": membership.get("joined_at"),
                    "left_at": membership.get("left_at"),
                    "role": membership.get("role"),
                }
            )

    return sorted(
        rows,
        key=lambda row: (
            row.get("group_id") or "",
            row.get("person_id") or "",
            row.get("joined_at") or "",
        ),
    )

def build_event_summary_table_rows(output: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []

    for group in output["groups"]:
        group_type = group.get("group_type") or {}

        for event in group.get("events", []):
            attendance = event.get("attendance", {})

            rows.append(
                {
                    "group_id": group.get("id"),
                    "group_name": group.get("name"),
                    "group_type_id": group.get("group_type_id"),
                    "group_type_name": group_type.get("name"),
                    "event_id": event.get("id"),
                    "event_name": event.get("name"),
                    "starts_at": event.get("starts_at"),
                    "ends_at": event.get("ends_at"),
                    "classification": event.get("event_time_classification"),
                    "canceled": event.get("canceled"),
                    "attendance_records": attendance.get("attendance_record_count"),
                    "attended_count": attendance.get("attended_count"),
                    "attendance_rate": attendance.get("attendance_rate"),
                    "visitors_count": event.get("visitors_count"),
                }
            )

    return rows

def build_event_instances_table_rows(
    events: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    rows = []

    for event in events:
        rows.append(
            {
                "event_instance_id": event.get("id"),
                "event_id": event.get("parent_event_id"),
                "group_id": event.get("group_id"),
                "name": event.get("name"),
                "description": event.get("description"),
                "starts_at": event.get("starts_at"),
                "ends_at": event.get("ends_at"),
                "canceled": event.get("canceled"),
                "canceled_at": event.get("canceled_at"),
                "multi_day": event.get("multi_day"),
                "location_type_preference": event.get(
                    "location_type_preference"
                ),
                "virtual_location_url": event.get(
                    "virtual_location_url"
                ),
                "visitors_count": event.get("visitors_count"),
                "attendance_requests_enabled": event.get(
                    "attendance_requests_enabled"
                ),
                "automated_reminder_enabled": event.get(
                    "automated_reminder_enabled"
                ),
                "reminders_sent": event.get("reminders_sent"),
                "reminders_sent_at": event.get(
                    "reminders_sent_at"
                ),
                "attendance_submitter_id": event.get(
                    "attendance_submitter_id"
                ),
                "location_id": event.get("location_id"),
                "classification": event.get(
                    "event_time_classification"
                ),
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            row.get("group_id") or "",
            parse_pco_datetime(row.get("starts_at"))
            or datetime.max.replace(tzinfo=timezone.utc),
            row.get("event_instance_id") or "",
        ),
    )


def build_events_table_rows(
    event_instances: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    events_by_id: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for instance in event_instances:
        event_id = instance.get("parent_event_id")

        if event_id:
            events_by_id[event_id].append(instance)

    rows = []

    for event_id, instances in events_by_id.items():
        sorted_instances = sorted(
            instances,
            key=lambda instance: (
                parse_pco_datetime(instance.get("starts_at"))
                or datetime.max.replace(tzinfo=timezone.utc)
            ),
        )

        first_instance = sorted_instances[0]
        last_instance = sorted_instances[-1]
        repeating_event_id = first_instance.get(
            "repeating_event_id"
        )

        rows.append(
            {
                "event_id": event_id,
                "pco_repeating_event_id": repeating_event_id,
                "group_id": first_instance.get("group_id"),
                "name": first_instance.get("name"),
                "description": first_instance.get("description"),
                "repeating": repeating_event_id is not None,
                "instance_count": len(sorted_instances),
                "first_instance_starts_at": first_instance.get(
                    "starts_at"
                ),
                "last_instance_starts_at": last_instance.get(
                    "starts_at"
                ),
                "location_type_preference": first_instance.get(
                    "location_type_preference"
                ),
                "virtual_location_url": first_instance.get(
                    "virtual_location_url"
                ),
                "location_id": first_instance.get("location_id"),
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            row.get("group_id") or "",
            parse_pco_datetime(
                row.get("first_instance_starts_at")
            )
            or datetime.max.replace(tzinfo=timezone.utc),
            row.get("event_id") or "",
        ),
    )


def build_tag_groups_table_rows(
    tag_groups: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    return [
        {
            "tag_group_id": tag_group.get("tag_group_id"),
            "name": tag_group.get("name"),
            "display_publicly": tag_group.get(
                "display_publicly"
            ),
            "multiple_options_enabled": tag_group.get(
                "multiple_options_enabled"
            ),
        }
        for tag_group in tag_groups
    ]


def build_tags_table_rows(
    tags: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    return [
        {
            "tag_id": tag.get("tag_id"),
            "tag_group_id": tag.get("tag_group_id"),
            "name": tag.get("name"),
        }
        for tag in tags
    ]


def build_group_tags_table_rows(
    group_tags: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    seen = set()
    rows = []

    for group_tag in group_tags:
        key = (
            group_tag.get("group_id"),
            group_tag.get("tag_id"),
        )

        if key in seen:
            continue

        seen.add(key)

        rows.append(
            {
                "group_id": group_tag.get("group_id"),
                "tag_id": group_tag.get("tag_id"),
            }
        )

    return rows


def build_all_attendance_table_rows(
    output: Dict[str, Any],
) -> List[Dict[str, Any]]:
    rows = []

    for group in output.get("groups", []):
        group_id = group.get("id")
        group_name = group.get("name")

        group_type = group.get("group_type") or {}
        group_type_id = group.get("group_type_id")

        memberships = group.get("memberships", [])

        members_by_person_id = {
            membership.get("person_id"): membership
            for membership in memberships
            if membership.get("person_id")
        }

        for event in group.get("events", []):
            attendance = event.get("attendance", {})
            attendance_records = attendance.get(
                "all_attendance_records",
                [],
            )

            attendance_by_person_id = {
                record.get("person_id"): record
                for record in attendance_records
                if record.get("person_id")
            }

            # Include:
            # 1. Current group members, even if they have no attendance record.
            # 2. People with an attendance record who are not current members.
            all_person_ids = (
                set(members_by_person_id.keys())
                | set(attendance_by_person_id.keys())
            )

            for person_id in sorted(all_person_ids):
                membership = members_by_person_id.get(person_id)
                attendance_record = attendance_by_person_id.get(person_id)

                person = None

                if attendance_record:
                    person = attendance_record.get("person")

                if not person and membership:
                    person = membership.get("person")

                attendance_record_exists = attendance_record is not None

                attended = (
                    attendance_record.get("attended")
                    if attendance_record_exists
                    else None
                )

                rows.append(
                    {
                        "group_id": group_id,
                        "group_name": group_name,
                        "group_type_id": group_type_id,
                        "event_instance_id": event.get("id"),
                        "event_name": event.get("name"),
                        "starts_at": event.get("starts_at"),
                        "ends_at": event.get("ends_at"),
                        "classification": event.get(
                            "event_time_classification"
                        ),
                        "event_canceled": event.get("canceled"),
                        "person_id": person_id,
                        "member_name": full_name(person),
                        "first_name": (
                            person.get("first_name")
                            if person
                            else ""
                        ),
                        "last_name": (
                            person.get("last_name")
                            if person
                            else ""
                        ),
                        "current_group_member": membership is not None,
                        "membership_id": (
                            membership.get("id")
                            if membership
                            else None
                        ),
                        "membership_role": (
                            membership.get("role")
                            if membership
                            else ""
                        ),
                        "joined_at": (
                            membership.get("joined_at")
                            if membership
                            else None
                        ),
                        "attendance_id": (
                            attendance_record.get("id")
                            if attendance_record
                            else None
                        ),
                        "attendance_role": (
                            attendance_record.get("role")
                            if attendance_record
                            else ""
                        ),
                        "attended": attended,
                        "attendance_record_exists": (
                            attendance_record_exists
                        ),
                    }
                )

    return sorted(
        rows,
        key=lambda row: (
            row.get("group_name") or "",
            parse_pco_datetime(row.get("starts_at"))
            or datetime.max.replace(tzinfo=timezone.utc),
            row.get("last_name") or "",
            row.get("first_name") or "",
            row.get("person_id") or "",
        ),
    )



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Planning Center Groups API tester/exporter."
    )

    parser.add_argument(
        "--mode",
        choices=["past", "future", "all"],
        default="all",
        help="Which events to include after fetching events.",
    )

    parser.add_argument(
        "--past-limit",
        type=int,
        default=None,
        help="Maximum number of past events per group. Default: no limit.",
    )

    parser.add_argument(
        "--future-limit",
        type=int,
        default=None,
        help="Maximum number of future events per group. Default: no limit.",
    )

    parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Include archived groups.",
    )

    parser.add_argument(
        "--skip-memberships",
        action="store_true",
        help="Skip group memberships fetch.",
    )

    parser.add_argument(
        "--skip-attendance",
        action="store_true",
        help="Skip event attendance fetch.",
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Parallel workers for memberships and attendance.",
    )

    parser.add_argument(
        "--max-event-pages",
        type=int,
        default=None,
        help="Optional safety limit for event pagination pages.",
    )

    parser.add_argument(
        "--group-limit",
        type=int,
        default=None,
        help="Maximum number of groups to process. Default: no limit.",
    )

    return parser.parse_args()


def main() -> int:
    t0 = time.perf_counter()
    args = parse_args()

    app_id = os.getenv("PCO_APP_ID")
    secret = os.getenv("PCO_SECRET")

    if not app_id or not secret:
        print(
            "Missing credentials. Set PCO_APP_ID and PCO_SECRET environment variables.",
            file=sys.stderr,
        )
        return 2

    if args.past_limit is not None and args.past_limit < 0:
        print("--past-limit must be >= 0", file=sys.stderr)
        return 2

    if args.future_limit is not None and args.future_limit < 0:
        print("--future-limit must be >= 0", file=sys.stderr)
        return 2
    
    if args.group_limit is not None and args.group_limit < 0:
        print("--group-limit must be >= 0", file=sys.stderr)
        return 2

    workers = max(1, args.workers)
    client = PlanningCenterClient(app_id=app_id, secret=secret)

    print("Fetching group types...")
    group_types = fetch_group_types(client)

    print(f"Fetched {len(group_types)} group types.")

    print("Fetching groups...")
    groups = fetch_groups(client, include_archived=args.include_archived)

    if args.group_limit is not None:
        groups = groups[:args.group_limit]

    group_ids = {group["id"] for group in groups}

    print("Fetching tag groups...")
    tag_groups = fetch_tag_groups(client)

    print(f"Fetched {len(tag_groups)} tag groups.")

    print("Fetching tags...")
    tags = fetch_all_tags(
        client=client,
        tag_groups=tag_groups,
        workers=workers,
    )

    print(f"Fetched {len(tags)} tags.")

    print("Fetching group tags...")
    group_tags = fetch_group_tags(
        client=client,
        groups=groups,
        workers=workers,
    )

    print(f"Fetched {len(group_tags)} group-tag relationships.")


    print("Fetching events...")
    all_events = fetch_events(client, max_event_pages=args.max_event_pages)
    all_events = [event for event in all_events if event.get("group_id") in group_ids]

    selected_events = classify_and_limit_events(
        events=all_events,
        mode=args.mode,
        past_limit=args.past_limit,
        future_limit=args.future_limit,
    )

    memberships_by_group: Dict[str, List[Dict[str, Any]]] = {}

    if not args.skip_memberships:
        print("Fetching memberships...")
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(fetch_memberships_for_group, client, group["id"]): group["id"]
                for group in groups
            }

            for future in as_completed(future_map):
                group_id = future_map[future]

                try:
                    memberships_by_group[group_id] = future.result()
                except Exception as exc:
                    print(f"Membership fetch failed for group_id={group_id}: {exc}", file=sys.stderr)
                    memberships_by_group[group_id] = []

    attendance_by_event: Dict[str, Dict[str, Any]] = {}

    if not args.skip_attendance:
        print("Fetching attendance...")
        attendance_by_event = fetch_attendance_for_events(
            client=client,
            events=selected_events,
            workers=workers,
        )

    output = build_output(
        groups=groups,
        group_types=group_types,
        memberships_by_group=memberships_by_group,
        events=selected_events,
        attendance_by_event=attendance_by_event,
    )

    convert_output_datetimes_to_local_sql(output)

    group_type_rows = build_group_types_table_rows(output)
    group_overview_rows = build_group_overview_table_rows(output)
    group_members_rows = build_group_members_table_rows(output)
    group_membership_rows = build_group_memberships_table_rows(output)
    event_summary_rows = build_event_summary_table_rows(output)
    all_attendance_rows = build_all_attendance_table_rows(output)
    event_instances_rows = build_event_instances_table_rows(selected_events)
    events_rows = build_events_table_rows(selected_events)
    tag_groups_rows = build_tag_groups_table_rows(tag_groups)
    tags_rows = build_tags_table_rows(tags)
    group_tags_rows = build_group_tags_table_rows(group_tags)


    #convert_output_datetimes_to_local_sql(event_instances_rows)
    #convert_output_datetimes_to_local_sql(events_rows)

    print("Done.")
    print(f"Group types: {output['summary']['group_type_count']}")
    print(f"Groups: {output['summary']['group_count']}")
    print(f"Events returned: {output['summary']['event_count']}")
    print(
        "Attendance events returned: "
        f"{output['summary']['attendance_event_count']}"
    )
    print(f"Combined attendance table rows: {len(all_attendance_rows)}")
    print(f"Group membership rows: {len(group_membership_rows)}")

    attendance_records_present = sum(
        1
        for row in all_attendance_rows
        if row.get("attendance_record_exists")
    )

    rows_without_attendance_record = sum(
        1
        for row in all_attendance_rows
        if not row.get("attendance_record_exists")
    )

    attended_rows = sum(
        1
        for row in all_attendance_rows
        if row.get("attendance_record_exists")
        and row.get("attended") is True
    )

    print(f"Actual attendance records: {attendance_records_present}")
    print(f"Records marked attended: {attended_rows}")
    print(
        "Member-event rows without attendance records: "
        f"{rows_without_attendance_record}"
    )

    print_table(
        title="Group Overview",
        rows=group_overview_rows,
        columns=[
            "group_id",
            "group_name",
            "group_type_id",
            "member_count",
            "pco_memberships_count",
            "event_count",
            "total_attended",
            "total_attendance_records",
            "created_at",
            "archived_at",
        ],
        limit=10,
    )

    print_table(
        title="Group Types",
        rows=group_type_rows,
        columns=[
            "group_type_id",
            "group_type_name",
            "church_center_visible",
            "group_count",
        ],
        limit=None,
    )

    print_table(
        title="Group Members",
        rows=group_members_rows,
        columns=[
            "group_id",
            #"group_name",
            #"group_type_id",
            "membership_id",
            "person_id",
            #"member_name",
            "role",
            "joined_at",
        ],
        limit=50,
    )

    print_table(
        title="Group Memberships",
        rows=group_membership_rows,
        columns=[
            "membership_id",
            "group_id",
            "person_id",
            "joined_at",
            "left_at",
            "role",
        ],
        limit=100,
    )

    
    """print_table(
        title="Event Summary",
        rows=event_summary_rows,
        columns=[
            "group_id",
            "group_name",
            "group_type_id",
            "group_type_name",
            "event_id",
            "event_name",
            "starts_at",
            "ends_at",
            "classification",
            "canceled",
            "attendance_records",
            "attended_count",
            "attendance_rate",
            "visitors_count",
        ],
        limit=50,
    )"""

    print_table(
        title="All Group Event Attendances",
        rows=all_attendance_rows,
        columns=[
            #"group_id",
            #"group_name",
            "event_id",
            "event_name",
            #"starts_at",
            "person_id",
            #"member_name",
            "current_group_member",
            "membership_role",
            "attendance_id",
            "attendance_role",
            "attended",
            "attendance_record_exists",
        ],
        limit=100,
    )

    print_table(
        title="Events",
        rows=events_rows,
        columns=[
            "event_id",
            "pco_repeating_event_id",
            "group_id",
            "name",
            "repeating",
            "instance_count",
            #"first_instance_starts_at",
            #"last_instance_starts_at",
            "location_type_preference",
            "location_id",
        ],
        limit=50,
    )

    print_table(
        title="Event Instances",
        rows=event_instances_rows,
        columns=[
            "event_instance_id",
            "event_id",
            #"group_id",
            "name",
            "starts_at",
            "ends_at",
            "canceled",
            "visitors_count",
            "classification",
            "location_id",
        ],
        limit=50,
    )

    print_table(
        title="Tag Groups",
        rows=tag_groups_rows,
        columns=[
            "tag_group_id",
            "name",
            "display_publicly",
            "multiple_options_enabled",
        ],
        limit=50,
    )

    print_table(
        title="Tags",
        rows=tags_rows,
        columns=[
            "tag_id",
            "tag_group_id",
            "name",
        ],
        limit=30,
    )

    print_table(
        title="Group Tags",
        rows=group_tags_rows,
        columns=[
            "group_id",
            "tag_id",
        ],
        limit=50,
    )


    
    t1 = time.perf_counter()
    print(f"Total time taken: {t1 - t0:.2f}" )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
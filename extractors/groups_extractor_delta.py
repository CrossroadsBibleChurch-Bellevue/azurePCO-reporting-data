#!/usr/bin/env python3

import sys
import time
import os
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin


from utils.env_fetcher import get_auth_from_env, max_event_pages, max_workers, skip_attendance, skip_memberships, mode, include_archived
from utils.hasher import stable_hash_id

import requests


BASE_URL = "https://api.planningcenteronline.com/groups/v2/"
DEFAULT_PER_PAGE = 100


class PCOApiError(RuntimeError):
    pass


def parse_pco_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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
        "email_addresses": attrs.get("email_addresses"),
        "phone_numbers": attrs.get("phone_numbers"),
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
        "person": compact_person(included_people_by_id.get(person_id)),
    }


def compact_event(event: Dict[str, Any]) -> Dict[str, Any]:
    attrs = event.get("attributes", {})

    return {
        "id": event.get("id"),
        "group_id": rel_id(event, "group"),
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
        "attendance_requests_enabled": attrs.get("attendance_requests_enabled"),
        "attendance_submitter_id": rel_id(event, "attendance_submitter"),
        "location_id": rel_id(event, "location"),
        "repeating_event_id": rel_id(event, "repeating_event"),
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


def classify_and_limit_events(
    events: List[Dict[str, Any]],
    mode: str,
    past_limit: Optional[int],
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
                future_events
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
    memberships_by_group: Dict[str, List[Dict[str, Any]]],
    events: List[Dict[str, Any]],
    attendance_by_event: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    events_by_group = defaultdict(list)

    for event in events:
        attendance = attendance_by_event.get(event["id"], {})
        event["attendance"] = attendance
        events_by_group[event.get("group_id")].append(event)

    output_groups = []

    for group in groups:
        group_id = group["id"]
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
            "group_count": len(output_groups),
            "event_count": len(events),
            "attendance_event_count": len(attendance_by_event),
        },
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


def build_group_overview_table_rows(output: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []

    for group in output["groups"]:
        analytics = group.get("analytics", {})
        memberships = group.get("memberships", [])
        events = group.get("events", [])

        attended_total = analytics.get("total_attended_count_across_returned_events") or 0
        attendance_records_total = analytics.get("total_attendance_records_across_returned_events") or 0

        overall_attendance_rate = (
            round(attended_total / attendance_records_total, 4)
            if attendance_records_total
            else None
        )

        rows.append(
            {
                "hash_id": stable_hash_id("group_overview", group.get("id")),
                "group_id": group.get("id"),
                "group_name": group.get("name"),
                "member_count": len(memberships),
                "pco_memberships_count": group.get("memberships_count"),
                "event_count": len(events),
                "avg_event_attendance_rate": analytics.get("average_event_attendance_rate"),
                "overall_attendance_rate": overall_attendance_rate,
                "total_attended": attended_total,
                "total_attendance_records": attendance_records_total,
                "archived_at": group.get("archived_at"),
            }
        )

    return rows

def build_group_members_table_rows(output: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    month = datetime.now().strftime("%B")
    year = datetime.now().year
    snapshot = f"{month}_{year}"

    for group in output["groups"]:
        group_id = group.get("id")
        group_name = group.get("name")

        for membership in group.get("memberships", []):
            person = membership.get("person")

            rows.append(
                {
                    "hash_id": stable_hash_id(f"snapshot_{snapshot}", group_id, membership.get("person_id")),
                    "group_id": group_id,
                    "group_name": group_name,
                    "membership_id": membership.get("id"),
                    "person_id": membership.get("person_id"),
                    "member_name": full_name(person),
                    "first_name": person.get("first_name") if person else "",
                    "last_name": person.get("last_name") if person else "",
                    "role": membership.get("role"),
                    "joined_at": membership.get("joined_at"),
                    "email_addresses": person.get("email_addresses") if person else "",
                    "phone_numbers": person.get("phone_numbers") if person else "",
                }
            )

    return rows

def build_event_summary_table_rows(output: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []

    for group in output["groups"]:
        for event in group.get("events", []):
            attendance = event.get("attendance", {})

            rows.append(
                {
                    "group_id": group.get("id"),
                    "group_name": group.get("name"),
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

def build_member_attendance_tables_by_group(
    output: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    tables_by_group = {}

    for group in output["groups"]:
        group_id = group.get("id")
        group_name = group.get("name")

        memberships = group.get("memberships", [])
        members_by_person_id = {
            membership.get("person_id"): membership
            for membership in memberships
            if membership.get("person_id")
        }

        rows = []

        for event in group.get("events", []):
            attendance = event.get("attendance", {})
            attendance_records = attendance.get("all_attendance_records", [])

            attendance_by_person_id = {
                record.get("person_id"): record
                for record in attendance_records
                if record.get("person_id")
            }

            all_person_ids = set(members_by_person_id.keys()) | set(attendance_by_person_id.keys())

            for person_id in sorted(all_person_ids):
                membership = members_by_person_id.get(person_id)
                attendance_record = attendance_by_person_id.get(person_id)

                person = None

                if attendance_record:
                    person = attendance_record.get("person")

                if not person and membership:
                    person = membership.get("person")

                attended = (
                    attendance_record.get("attended")
                    if attendance_record is not None
                    else False
                )

                rows.append(
                    {   
                        "hash_id": stable_hash_id("member_attendance", event.get("id"), person_id),
                        "event_id": event.get("id"),
                        "group_id": group_id,
                        "event_name": event.get("name"),
                        "starts_at": event.get("starts_at"),
                        "person_id": person_id,
                        "member_name": full_name(person),
                        "membership_role": membership.get("role") if membership else "",
                        "attendance_role": attendance_record.get("role") if attendance_record else "",
                        "attended": attended,
                        "attendance_record_exists": attendance_record is not None,
                    }
                )

        tables_by_group[group_id] = {
            "group_id": group_id,
            "group_name": group_name,
            "rows": rows,
        }

    return tables_by_group



def extraction() -> Dict[str, Dict[str, Any]]:
    t0 = time.perf_counter()

    app_id, secret = get_auth_from_env()

    past_limit = 10

    workers = max(1, int(max_workers))
    client = PlanningCenterClient(app_id=app_id, secret=secret)

    logging.info("Fetching groups...")
    groups = fetch_groups(client, include_archived=include_archived)

    group_ids = {group["id"] for group in groups}

    logging.info("Fetching events...")
    all_events = fetch_events(client, max_event_pages=max_event_pages)
    all_events = [event for event in all_events if event.get("group_id") in group_ids]

    selected_events = classify_and_limit_events(
        events=all_events,
        mode=mode,
        past_limit=past_limit,
    )

    memberships_by_group: Dict[str, List[Dict[str, Any]]] = {}

    if not skip_memberships:
        logging.info("Fetching memberships...")
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

    if not skip_attendance:
        logging.info("Fetching attendance...")
        attendance_by_event = fetch_attendance_for_events(
            client=client,
            events=selected_events,
            workers=workers,
        )

    output = build_output(
        groups=groups,
        memberships_by_group=memberships_by_group,
        events=selected_events,
        attendance_by_event=attendance_by_event,
    )

    group_overview_rows = build_group_overview_table_rows(output)
    attendance_tables_by_group = build_member_attendance_tables_by_group(output)



    t1 = time.perf_counter()
    logging.info(f"Total time taken: {t1 - t0:.2f}" )

    return {
        "group_overview": list(group_overview_rows),
        "group_attendance": list(attendance_tables_by_group.values())
    }

def main() -> int:
    raise SystemExit(extraction())


if __name__ == "__main__":
    raise SystemExit(main())
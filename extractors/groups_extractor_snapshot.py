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


from utils.env_fetcher import get_auth_from_env, max_event_pages, max_workers, group_limit, past_limit, future_limit, skip_attendance, skip_memberships, mode, include_archived
from utils.hasher import stable_hash_id

import requests


BASE_URL = "https://api.planningcenteronline.com/groups/v2/"
DEFAULT_PER_PAGE = 100


class PCOApiError(RuntimeError):
    pass


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




def build_output(
    groups: List[Dict[str, Any]],
    memberships_by_group: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    output_groups = []

    for group in groups:
        group_id = group["id"]
        memberships = memberships_by_group.get(group_id, [])

        group["memberships"] = memberships

        output_groups.append(group)

    return {
        "generated_at": now_utc().isoformat(),
        "summary": {
            "group_count": len(output_groups),
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


def full_name(person: Optional[Dict[str, Any]]) -> str:
    if not person:
        return ""

    first_name = person.get("first_name") or ""
    last_name = person.get("last_name") or ""

    return f"{first_name} {last_name}".strip()


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


def extraction() -> Dict[str, Dict[str, Any]]:
    t0 = time.perf_counter()

    app_id, secret = get_auth_from_env()
    
    workers = max(1, int(max_workers))
    client = PlanningCenterClient(app_id=app_id, secret=secret)

    groups = fetch_groups(client, include_archived=include_archived)
    if group_limit is not None:
        groups = groups[:group_limit]

    memberships_by_group: Dict[str, List[Dict[str, Any]]] = {}

    if not skip_memberships:
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
                    memberships_by_group[group_id] = []


    output = build_output(
        groups=groups,
        memberships_by_group=memberships_by_group,
    )

    group_members_rows = build_group_members_table_rows(output)

    t1 = time.perf_counter()
    print(f"Total time taken: {t1 - t0:.2f}" )

    return {
        "group_snapshot": list(group_members_rows)
    }

def main() -> int:
    raise SystemExit(extraction())


if __name__ == "__main__":
    raise SystemExit(main())
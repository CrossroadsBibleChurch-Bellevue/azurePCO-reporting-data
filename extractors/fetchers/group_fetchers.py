from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List, Optional, Tuple
import requests
import time
import logging
import sys

from utils. response_parsers import rel_id
from urllib.parse import urljoin
from utils.compactors import compact_event, compact_group, compact_group_type, compact_membership, compact_person, compact_tag, compact_tag_group


BASE_URL = "https://api.planningcenteronline.com/groups/v2/"

class PCOApiError(RuntimeError):
    pass


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
        params.setdefault("per_page", 100)

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
                logging.info(
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
                logging.info(
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
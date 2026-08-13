#!/usr/bin/env python3

import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import logging

from typing import Any, Dict, List, Optional


from utils.env_fetcher import get_auth_from_env, max_event_pages, mode, past_limit, future_limit, group_limit
from extractors.builders.group_builders import build_tags_table_rows, build_tag_groups_table_rows, build_output, build_group_types_table_rows, build_group_tags_table_rows, build_group_overview_table_rows, build_group_memberships_table_rows, build_group_members_table_rows, build_events_table_rows, build_event_instances_table_rows, build_all_attendance_table_rows
from utils.time_functions import parse_pco_datetime, convert_output_datetimes_to_local_sql, now_utc
from extractors.fetchers.group_fetchers import fetch_all_tags, fetch_events, fetch_group_tags, fetch_group_types, fetch_groups, fetch_memberships_for_group, fetch_tag_groups, fetch_attendance_for_events, PlanningCenterClient
from database.prepper import wake_up_server


# Groups extractor delta version. To make it delta I just have it fetch the last couple events (5) since my assumption is that will be all that would change if any.
# Also made it delta this way because the attendance endpoint can't be queried or ordered by updated_at so this is an easier way to do it


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



def extraction() -> Dict[str, List[Dict[str, Any]]]:
    t0 = time.perf_counter()

    app_id, secret = get_auth_from_env()

    if not app_id or not secret:
        logging.info(
            "Missing credentials. Set PCO_APP_ID and PCO_SECRET environment variables.",
            file=sys.stderr,
        )
        return 2

    if past_limit is not None and past_limit < 0:
        logging.info("--past-limit must be >= 0", file=sys.stderr)
        return 2

    if future_limit is not None and future_limit < 0:
        logging.info("--future-limit must be >= 0", file=sys.stderr)
        return 2
    
    if group_limit is not None and group_limit < 0:
        logging.info("--group-limit must be >= 0", file=sys.stderr)
        return 2

    workers = 8
    client = PlanningCenterClient(app_id=app_id, secret=secret)

    logging.info("Fetching group types...")
    group_types = fetch_group_types(client)

    logging.info(f"Fetched {len(group_types)} group types.")

    logging.info("Fetching groups...")
    groups = fetch_groups(client, include_archived=True)

    group_ids = {group["id"] for group in groups}

    logging.info("Fetching tag groups...")
    tag_groups = fetch_tag_groups(client)

    logging.info(f"Fetched {len(tag_groups)} tag groups.")

    logging.info("Fetching tags...")
    tags = fetch_all_tags(
        client=client,
        tag_groups=tag_groups,
        workers=workers,
    )

    logging.info(f"Fetched {len(tags)} tags.")

    logging.info("Fetching group tags...")
    group_tags = fetch_group_tags(
        client=client,
        groups=groups,
        workers=workers,
    )

    logging.info(f"Fetched {len(group_tags)} group-tag relationships.")

    wake_up_server()
    logging.info("Fetching events...")
    all_events = fetch_events(client, max_event_pages=max_event_pages)
    all_events = [event for event in all_events if event.get("group_id") in group_ids]

    selected_events = classify_and_limit_events(
        events=all_events,
        mode=mode,
        past_limit=past_limit,
        future_limit=future_limit,
    )

    wake_up_server()
    memberships_by_group: Dict[str, List[Dict[str, Any]]] = {}

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
                logging.info(f"Membership fetch failed for group_id={group_id}: {exc}", file=sys.stderr)
                memberships_by_group[group_id] = []

    attendance_by_event: Dict[str, Dict[str, Any]] = {}

    wake_up_server()
    logging.info("Fetching attendance records...")

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
    all_attendance_rows = build_all_attendance_table_rows(output)
    event_instances_rows = build_event_instances_table_rows(selected_events)
    events_rows = build_events_table_rows(selected_events)
    tag_groups_rows = build_tag_groups_table_rows(tag_groups)
    tags_rows = build_tags_table_rows(tags)
    group_tags_rows = build_group_tags_table_rows(group_tags)

    logging.info("Done.")
    
    t1 = time.perf_counter()
    logging.info(f"Total time taken: {t1 - t0:.2f}" )

    return {
        "group_overview": list(group_overview_rows),
        "group_types": list(group_type_rows),
        "group_tags": list(group_tags_rows),
        "tags": list(tags_rows),
        "tag_groups": list(tag_groups_rows),
        "events": list(events_rows),
        "event_instances": list(event_instances_rows),
        "event_attendances": list(all_attendance_rows),
        "group_members": list(group_members_rows),
        "group_members_history": list(group_membership_rows),
    }


def main():
    raise SystemError(extraction())

if __name__ == "__main__":
    raise SystemExit(main())
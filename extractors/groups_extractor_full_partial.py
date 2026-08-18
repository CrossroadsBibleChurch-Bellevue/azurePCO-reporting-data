#!/usr/bin/env python3

import gc
import logging
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence

from database.prepper import wake_up_server
from extractors.builders.group_builders import (
    build_event_instances_table_rows,
    build_events_table_rows,
    build_group_members_table_rows,
    build_group_memberships_table_rows,
    build_group_overview_table_rows,
    build_group_tags_table_rows,
    build_group_types_table_rows,
    build_output,
    build_tag_groups_table_rows,
    build_tags_table_rows,
)
from extractors.fetchers.group_fetchers import (
    PlanningCenterClient,
    fetch_all_tags,
    fetch_events,
    fetch_group_tags,
    fetch_group_types,
    fetch_groups,
    fetch_memberships_for_group,
    fetch_tag_groups,
)
from utils.env_fetcher import get_auth_from_env, max_event_pages
from utils.time_functions import (
    convert_output_datetimes_to_local_sql,
    now_utc,
    parse_pco_datetime,
)


def classify_and_limit_events(
    events: List[Dict[str, Any]],
    mode: str,
    past_limit: Optional[int],
    future_limit: Optional[int],
) -> List[Dict[str, Any]]:
    """
    Classify events as past or future per group and apply optional limits.

    Unknown-date events are excluded because they cannot be classified safely.
    """

    if mode not in {"past", "future", "all"}:
        raise ValueError("mode must be 'past', 'future', or 'all'.")

    current_time = now_utc()

    events_by_group: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(
        lambda: {
            "past": [],
            "future": [],
        }
    )

    for event in events:
        group_id = event.get("group_id")

        if group_id is None:
            continue

        group_id = str(group_id)

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

        if mode in {"past", "all"}:
            selected_events.extend(
                past_events[:past_limit]
                if past_limit is not None
                else past_events
            )

        if mode in {"future", "all"}:
            selected_events.extend(
                future_events[:future_limit]
                if future_limit is not None
                else future_events
            )

    return sorted(
        selected_events,
        key=lambda event: (
            str(event.get("group_id") or ""),
            parse_pco_datetime(event.get("starts_at"))
            or datetime.max.replace(tzinfo=timezone.utc),
        ),
    )


def iter_row_chunks(
    rows: Iterable[Dict[str, Any]],
    batch_size: int = 5000,
) -> Iterator[List[Dict[str, Any]]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero.")

    batch: List[Dict[str, Any]] = []
    chunk_number = 0

    for row in rows:
        batch.append(row)

        if len(batch) >= batch_size:
            chunk_number += 1

            logging.info(
                "Yielding row chunk %d with %d records.",
                chunk_number,
                len(batch),
            )

            yield batch
            batch = []

    if batch:
        chunk_number += 1

        logging.info(
            "Yielding final row chunk %d with %d records.",
            chunk_number,
            len(batch),
        )

        yield batch


def iter_list_chunks(
    items: Sequence[Dict[str, Any]],
    chunk_size: int,
) -> Iterator[List[Dict[str, Any]]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero.")

    for start in range(0, len(items), chunk_size):
        yield list(items[start:start + chunk_size])


def emit_table_chunks(
    table_name: str,
    rows: Iterable[Dict[str, Any]],
    batch_size: int,
) -> Iterator[Dict[str, List[Dict[str, Any]]]]:
    logging.info(
        "Preparing %s table chunks with batch_size=%d.",
        table_name,
        batch_size,
    )

    for chunk in iter_row_chunks(
        rows,
        batch_size=batch_size,
    ):
        logging.info(
            "Emitting %s chunk with %d rows.",
            table_name,
            len(chunk),
        )

        yield {
            table_name: chunk,
        }


def fetch_memberships_for_group_chunk(
    client: PlanningCenterClient,
    group_chunk: List[Dict[str, Any]],
    workers: int,
) -> Dict[str, List[Dict[str, Any]]]:
    memberships_by_group: Dict[str, List[Dict[str, Any]]] = {}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(
                fetch_memberships_for_group,
                client,
                str(group["id"]),
            ): str(group["id"])
            for group in group_chunk
            if group.get("id") is not None
        }

        for future in as_completed(future_map):
            group_id = future_map[future]

            try:
                memberships_by_group[group_id] = future.result()
            except Exception:
                logging.exception(
                    "Membership fetch failed for group_id=%s.",
                    group_id,
                )

                memberships_by_group[group_id] = []

    return memberships_by_group


def get_client() -> PlanningCenterClient:
    app_id, secret = get_auth_from_env()

    if not app_id or not secret:
        raise RuntimeError(
            "Missing PCO credentials. Set PCO_APP_ID and PCO_SECRET."
        )

    return PlanningCenterClient(
        app_id=app_id,
        secret=secret,
    )


def fetch_selected_events(
    client: PlanningCenterClient,
    valid_group_ids: set[str],
    *,
    mode: str = "all",
    past_limit: Optional[int] = None,
    future_limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch event instances belonging to the supplied Groups IDs.

    The returned records can be used to build both the events and
    event_instances tables. Their IDs can also be passed to the separate
    attendance extractor.
    """

    wake_up_server()

    logging.info("Fetching events...")

    all_events = fetch_events(
        client,
        max_event_pages=max_event_pages,
    )

    filtered_events = [
        event
        for event in all_events
        if (
            event.get("group_id") is not None
            and str(event["group_id"]) in valid_group_ids
        )
    ]

    del all_events
    gc.collect()

    selected_events = classify_and_limit_events(
        events=filtered_events,
        mode=mode,
        past_limit=past_limit,
        future_limit=future_limit,
    )

    del filtered_events
    gc.collect()

    logging.info(
        "Selected %d event instances.",
        len(selected_events),
    )

    return selected_events


def get_event_instance_ids(
    events: Iterable[Dict[str, Any]],
) -> List:
    """
    Extract unique non-null event instance IDs while preserving order.
    """

    event_instance_ids: List[str] = []
    seen_ids: set[str] = set()

    for event in events:
        event_instance_id = event.get("id")

        if event_instance_id is None:
            continue

        normalized_id = str(event_instance_id)

        if normalized_id in seen_ids:
            continue

        seen_ids.add(normalized_id)
        event_instance_ids.append(normalized_id)

    return event_instance_ids


def iter_extraction_chunks(
    *,
    batch_size: int = 5000,
    group_fetch_size: int = 25,
    event_fetch_size: int = 25,
) -> Iterator[Dict[str, List[Dict[str, Any]]]]:
    """
    Fetch and build all Groups extraction tables except event_attendances.

    Emitted tables:
        group_types
        group_tags
        tags
        tag_groups
        group_overview
        group_members
        group_members_history
        events
        event_instances
    """

    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero.")

    if group_fetch_size <= 0:
        raise ValueError("group_fetch_size must be greater than zero.")

    if event_fetch_size <= 0:
        raise ValueError("event_fetch_size must be greater than zero.")

    workers = 8
    client = get_client()

    logging.info("Fetching group types...")
    group_types = fetch_group_types(client)
    logging.info("Fetched %d group types.", len(group_types))

    logging.info("Fetching groups...")
    groups = fetch_groups(
        client,
        include_archived=True,
    )
    logging.info("Fetched %d groups.", len(groups))

    group_ids = {
        str(group["id"])
        for group in groups
        if group.get("id") is not None
    }

    logging.info("Fetching tag groups...")
    tag_groups = fetch_tag_groups(client)
    logging.info("Fetched %d tag groups.", len(tag_groups))

    logging.info("Fetching tags...")
    tags = fetch_all_tags(
        client=client,
        tag_groups=tag_groups,
        workers=workers,
    )
    logging.info("Fetched %d tags.", len(tags))

    logging.info("Fetching group tags...")
    group_tags = fetch_group_tags(
        client=client,
        groups=groups,
        workers=workers,
    )
    logging.info(
        "Fetched %d group-tag relationships.",
        len(group_tags),
    )

    yield from emit_table_chunks(
        "group_types",
        build_group_types_table_rows(
            {
                "group_types": group_types,
            }
        ),
        batch_size,
    )

    yield from emit_table_chunks(
        "group_tags",
        build_group_tags_table_rows(group_tags),
        batch_size,
    )

    yield from emit_table_chunks(
        "tags",
        build_tags_table_rows(tags),
        batch_size,
    )

    yield from emit_table_chunks(
        "tag_groups",
        build_tag_groups_table_rows(tag_groups),
        batch_size,
    )

    del tag_groups
    del tags
    del group_tags
    gc.collect()

    logging.info(
        "Fetching memberships in group chunks of %d.",
        group_fetch_size,
    )

    for group_chunk_number, group_chunk in enumerate(
        iter_list_chunks(groups, group_fetch_size),
        start=1,
    ):
        logging.info(
            "Processing membership group chunk %d with %d groups.",
            group_chunk_number,
            len(group_chunk),
        )

        wake_up_server()

        memberships_by_group = fetch_memberships_for_group_chunk(
            client=client,
            group_chunk=group_chunk,
            workers=workers,
        )

        membership_output = build_output(
            groups=group_chunk,
            group_types=group_types,
            memberships_by_group=memberships_by_group,
            events=[],
            attendance_by_event={},
        )

        convert_output_datetimes_to_local_sql(membership_output)

        yield from emit_table_chunks(
            "group_overview",
            build_group_overview_table_rows(membership_output),
            batch_size,
        )

        yield from emit_table_chunks(
            "group_members",
            build_group_members_table_rows(membership_output),
            batch_size,
        )

        yield from emit_table_chunks(
            "group_members_history",
            build_group_memberships_table_rows(membership_output),
            batch_size,
        )

        del memberships_by_group
        del membership_output
        del group_chunk
        gc.collect()

    events = fetch_selected_events(
        client=client,
        valid_group_ids=group_ids,
        mode="all",
        past_limit=None,
        future_limit=None,
    )

    logging.info(
        "Building %d event instances in chunks of %d.",
        len(events),
        event_fetch_size,
    )

    for event_chunk_number, event_chunk in enumerate(
        iter_list_chunks(events, event_fetch_size),
        start=1,
    ):
        logging.info(
            "Processing event metadata chunk %d with %d events.",
            event_chunk_number,
            len(event_chunk),
        )

        yield from emit_table_chunks(
            "events",
            build_events_table_rows(event_chunk),
            batch_size,
        )

        yield from emit_table_chunks(
            "event_instances",
            build_event_instances_table_rows(event_chunk),
            batch_size,
        )

        del event_chunk
        gc.collect()

    del events
    del groups
    del group_types
    del group_ids
    gc.collect()

    logging.info(
        "Finished emitting Groups extraction chunks without attendance."
    )


def extraction() -> Dict[str, List[Dict[str, Any]]]:
    """
    Collect all non-attendance extraction chunks into one dictionary.

    The streaming iterator should be preferred in memory-constrained
    Azure Functions.
    """

    start_time = time.perf_counter()

    collected: Dict[str, List[Dict[str, Any]]] = {}

    for batch in iter_extraction_chunks(
        batch_size=5000,
        group_fetch_size=25,
        event_fetch_size=25,
    ):
        for table_name, rows in batch.items():
            collected.setdefault(table_name, [])
            collected[table_name].extend(rows)

    elapsed = time.perf_counter() - start_time

    logging.info(
        "Non-attendance extraction completed in %.2f seconds.",
        elapsed,
    )

    return collected


def main() -> None:
    for batch in iter_extraction_chunks(
        batch_size=5000,
        group_fetch_size=25,
        event_fetch_size=25,
    ):
        for table_name, rows in batch.items():
            logging.info(
                "Generated table=%s rows=%d.",
                table_name,
                len(rows),
            )


if __name__ == "__main__":
    main()
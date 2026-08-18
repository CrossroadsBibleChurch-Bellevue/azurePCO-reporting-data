#!/usr/bin/env python3

import gc
import logging
import time
from typing import Any, Dict, Iterable, Iterator, List, Sequence

from database.prepper import wake_up_server
from extractors.builders.group_builders import (
    build_all_attendance_table_rows,
    build_output,
)
from extractors.fetchers.group_fetchers import (
    PlanningCenterClient,
    fetch_attendance_for_events,
)
from utils.env_fetcher import get_auth_from_env
from utils.time_functions import convert_output_datetimes_to_local_sql


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


def normalize_event_instance_ids(
    event_instance_ids: Iterable[Any],
) -> List:
    """
    Remove null and duplicate event instance IDs while preserving order.
    """

    normalized_ids: List[str] = []
    seen_ids: set[str] = set()

    for event_instance_id in event_instance_ids:
        if event_instance_id is None:
            continue

        normalized_id = str(event_instance_id).strip()

        if not normalized_id:
            continue

        if normalized_id in seen_ids:
            continue

        seen_ids.add(normalized_id)
        normalized_ids.append(normalized_id)

    return normalized_ids


def iter_id_chunks(
    event_instance_ids: Sequence[str],
    chunk_size: int,
) -> Iterator[List[str]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero.")

    for start in range(0, len(event_instance_ids), chunk_size):
        yield list(event_instance_ids[start:start + chunk_size])


def iter_row_chunks(
    rows: Iterable[Dict[str, Any]],
    batch_size: int,
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
                "Yielding attendance row chunk %d with %d records.",
                chunk_number,
                len(batch),
            )

            yield batch
            batch = []

    if batch:
        chunk_number += 1

        logging.info(
            "Yielding final attendance row chunk %d with %d records.",
            chunk_number,
            len(batch),
        )

        yield batch


def build_minimal_event_records(
    event_instance_ids: Sequence[str],
) -> List[Dict[str, Any]]:
    """
    Create the event dictionaries required by fetch_attendance_for_events.

    The existing attendance fetcher receives event dictionaries and uses
    each dictionary's id. Only the ID is needed for the attendance request.
    """

    return [
        {
            "id": event_instance_id,
        }
        for event_instance_id in event_instance_ids
    ]


def fetch_and_build_attendance_rows(
    client: PlanningCenterClient,
    event_instance_ids: Sequence[str],
    *,
    workers: int = 8,
) -> List[Dict[str, Any]]:
    """
    Fetch and build attendance rows for one bounded ID chunk.
    """

    if workers <= 0:
        raise ValueError("workers must be greater than zero.")

    if not event_instance_ids:
        return []

    event_records = build_minimal_event_records(event_instance_ids)

    attendance_by_event = fetch_attendance_for_events(
        client=client,
        events=event_records,
        workers=workers,
    )

    event_output = build_output(
        groups=[],
        group_types=[],
        memberships_by_group={},
        events=event_records,
        attendance_by_event=attendance_by_event,
    )

    convert_output_datetimes_to_local_sql(event_output)

    attendance_rows = build_all_attendance_table_rows(event_output)

    del attendance_by_event
    del event_output
    del event_records
    gc.collect()

    return attendance_rows


def iter_attendance_chunks(
    event_instance_ids: Iterable[Any],
    *,
    batch_size: int = 5000,
    event_fetch_size: int = 25,
    workers: int = 8,
) -> Iterator[Dict[str, List[Dict[str, Any]]]]:
    """
    Fetch, build, and yield event attendance rows.

    Parameters
    ----------
    event_instance_ids:
        PCO Groups event instance IDs.

    batch_size:
        Maximum number of built attendance rows emitted per yielded batch.

    event_fetch_size:
        Maximum number of event instance IDs fetched in one bounded chunk.

    workers:
        Number of concurrent attendance fetch workers.

    Yields
    ------
    Dictionaries in this format:

        {
            "event_attendances": [
                {...},
                {...},
            ]
        }
    """

    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero.")

    if event_fetch_size <= 0:
        raise ValueError("event_fetch_size must be greater than zero.")

    if workers <= 0:
        raise ValueError("workers must be greater than zero.")

    normalized_ids = normalize_event_instance_ids(event_instance_ids)

    if not normalized_ids:
        logging.info(
            "No event instance IDs were supplied for attendance extraction."
        )
        return

    client = get_client()

    logging.info(
        "Fetching attendance for %d event instances in chunks of %d.",
        len(normalized_ids),
        event_fetch_size,
    )

    for event_chunk_number, event_id_chunk in enumerate(
        iter_id_chunks(normalized_ids, event_fetch_size),
        start=1,
    ):
        logging.info(
            "Processing attendance event chunk %d with %d event instances.",
            event_chunk_number,
            len(event_id_chunk),
        )

        wake_up_server()

        attendance_rows = fetch_and_build_attendance_rows(
            client=client,
            event_instance_ids=event_id_chunk,
            workers=workers,
        )

        logging.info(
            "Built %d attendance rows for event chunk %d.",
            len(attendance_rows),
            event_chunk_number,
        )

        for attendance_row_chunk in iter_row_chunks(
            attendance_rows,
            batch_size=batch_size,
        ):
            yield {
                "event_attendances": attendance_row_chunk,
            }

        del attendance_rows
        del event_id_chunk
        gc.collect()

    del normalized_ids
    gc.collect()

    logging.info(
        "Finished emitting all attendance extraction chunks."
    )


def attendance_extraction(
    event_instance_ids: Iterable[Any],
    *,
    event_fetch_size: int = 25,
    workers: int = 8,
) -> List[Dict[str, Any]]:
    """
    Fetch and return all built attendance rows as one list.

    Use iter_attendance_chunks instead when memory usage is important.
    """

    start_time = time.perf_counter()

    attendance_rows: List[Dict[str, Any]] = []

    for batch in iter_attendance_chunks(
        event_instance_ids,
        batch_size=5000,
        event_fetch_size=event_fetch_size,
        workers=workers,
    ):
        attendance_rows.extend(
            batch["event_attendances"]
        )

    elapsed = time.perf_counter() - start_time

    logging.info(
        "Attendance extraction completed in %.2f seconds with %d rows.",
        elapsed,
        len(attendance_rows),
    )

    return attendance_rows


def main(event_instance_ids: Iterable[Any]) -> None:
    for batch in iter_attendance_chunks(
        event_instance_ids,
        batch_size=5000,
        event_fetch_size=25,
        workers=8,
    ):
        logging.info(
            "Generated table=event_attendances rows=%d.",
            len(batch["event_attendances"]),
        )


if __name__ == "__main__":
    raise RuntimeError(
        "Pass event instance IDs to main() or iter_attendance_chunks()."
    )
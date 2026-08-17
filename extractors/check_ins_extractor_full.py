#!/usr/bin/env python3

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

import gc
import logging


from utils.time_functions import convert_output_datetimes_to_local_sql
from extractors.fetchers.check_ins_shared import PCOError, Config, PCOClient, attrs, rel_id, getenv_blank_as_none, parse_date_env
from extractors.builders.check_ins_builders import build_checkin_event_attendance_rows, build_checkin_event_instance_rows, build_checkin_event_rows, build_event_time_rows, build_headcount_rows
from extractors.fetchers.check_ins_fetchers import fetch_events, fetch_attendance_types, fetch_event_checkins, fetch_event_periods, fetch_event_time_headcounts, fetch_location_event_times


# Same as check-ins extractor delta except fetches everything. Could be cleaned up since some function are reused, just haven't gotten to it.


load_dotenv()


def load_config() -> Config:
    app_id = getenv_blank_as_none("PCO_APP_ID")
    secret = getenv_blank_as_none("PCO_SECRET")

    if not app_id or not secret:
        raise ValueError("Missing required env vars: PCO_APP_ID and PCO_SECRET")

    max_events_raw = getenv_blank_as_none("PCO_MAX_EVENTS")
    max_events = int(max_events_raw) if max_events_raw else None

    max_workers_raw = getenv_blank_as_none("PCO_MAX_WORKERS")
    max_workers = int(max_workers_raw) if max_workers_raw else 8

    if max_workers < 1:
        raise ValueError("PCO_MAX_WORKERS must be >= 1")

    output_dir = Path(getenv_blank_as_none("PCO_OUTPUT_DIR") or ".")
    output_prefix = getenv_blank_as_none("PCO_OUTPUT_PREFIX") or "pco_checkins_test"


    return Config(
        app_id=app_id,
        secret=secret,
        event_id=getenv_blank_as_none("PCO_EVENT_ID"),
        start_date=parse_date_env("PCO_START_DATE"),
        end_date=parse_date_env("PCO_END_DATE"),
        checkin_updated_since=datetime(1970, 1, 1, tzinfo=timezone.utc),
        event_time_updated_since=datetime(1970, 1, 1, tzinfo=timezone.utc),
        output_dir=output_dir,
        output_prefix=output_prefix,
        max_events=max_events,
        max_workers=max_workers,
    )

_thread_local = threading.local()


def get_thread_client(config: Config) -> PCOClient:
    """
    Each worker thread gets its own PCOClient/session.

    requests.Session is not guaranteed to be thread-safe, so do not share
    the main client.session across threads.
    """
    client = getattr(_thread_local, "pco_client", None)

    if client is None:
        client = PCOClient(config.app_id, config.secret)
        _thread_local.pco_client = client

    return client



def index_resources(resources: Iterable[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for resource in resources:
        r_type = resource.get("type")
        r_id = resource.get("id")
        if r_type and r_id is not None:
            index[(r_type, str(r_id))] = resource
    return index

def iter_list_chunks(
    items: Sequence[dict[str, Any]],
    chunk_size: int,
) -> Iterator[list[dict[str, Any]]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero.")

    for start_index in range(0, len(items), chunk_size):
        yield list(items[start_index:start_index + chunk_size])


def iter_row_chunks(
    rows: Iterable[dict[str, Any]],
    batch_size: int,
) -> Iterator[list[dict[str, Any]]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero.")

    batch: list[dict[str, Any]] = []

    for row in rows:
        batch.append(row)

        if len(batch) >= batch_size:
            yield batch
            batch = []

    if batch:
        yield batch


def emit_table_chunks(
    table_name: str,
    rows: Iterable[dict[str, Any]],
    batch_size: int,
) -> Iterator[dict[str, list[dict[str, Any]]]]:
    for chunk_number, chunk in enumerate(
        iter_row_chunks(rows, batch_size),
        start=1,
    ):
        logging.info(
            "Emitting table '%s' chunk %d with %d rows.",
            table_name,
            chunk_number,
            len(chunk),
        )

        yield {table_name: chunk}


def threaded_fetch_attendance_types(config: Config, event_id: str) -> list[dict[str, Any]]:
    return fetch_attendance_types(get_thread_client(config), event_id)


def threaded_fetch_event_periods(config: Config, event_id: str) -> list[dict[str, Any]]:
    return fetch_event_periods(get_thread_client(config), event_id)


def threaded_fetch_event_checkins(config: Config, event_id: str) -> list[dict[str, Any]]:
    return fetch_event_checkins(get_thread_client(config), config, event_id)


def threaded_fetch_event_time_headcounts(config: Config, event_time_id: str) -> list[dict[str, Any]]:
    return fetch_event_time_headcounts(get_thread_client(config), event_time_id)


def threaded_fetch_location_event_times(config: Config, event_time_id: str) -> list[dict[str, Any]]:
    return fetch_location_event_times(get_thread_client(config), event_time_id)


def fetch_event_chunk_api_data(
    config: Config,
    event_chunk: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """
    Fetches all related resources for only the supplied event chunk.

    Returns:
        all_resources:
            Events, attendance types, periods, check-in payload resources,
            headcounts, and location-event-time resources.

        checkin_resources:
            CheckIn resources used to build attendance rows.
    """
    all_resources: list[dict[str, Any]] = []
    checkin_resources: list[dict[str, Any]] = []

    event_resource_blocks: dict[int, list[dict[str, Any]]] = {}
    event_checkin_payloads: dict[int, list[dict[str, Any]]] = {}
    event_time_ids_by_event_index: dict[int, set[str]] = {}

    with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
        # -----------------------------------------------------
        # First stage:
        # attendance types, periods, and check-ins per event.
        # -----------------------------------------------------

        first_stage_futures = {}

        for event_index, event in enumerate(event_chunk):
            event_id = str(event["id"])
            event_name = attrs(event).get("name") or "Unnamed event"

            attendance_future = executor.submit(
                threaded_fetch_attendance_types,
                config,
                event_id,
            )

            periods_future = executor.submit(
                threaded_fetch_event_periods,
                config,
                event_id,
            )

            checkins_future = executor.submit(
                threaded_fetch_event_checkins,
                config,
                event_id,
            )

            first_stage_futures[attendance_future] = (
                event_index,
                event_id,
                event_name,
                "attendance_types",
            )

            first_stage_futures[periods_future] = (
                event_index,
                event_id,
                event_name,
                "periods",
            )

            first_stage_futures[checkins_future] = (
                event_index,
                event_id,
                event_name,
                "checkins",
            )

        first_stage_results: dict[
            tuple[int, str],
            list[dict[str, Any]],
        ] = {}

        for future in as_completed(first_stage_futures):
            (
                event_index,
                event_id,
                event_name,
                fetch_kind,
            ) = first_stage_futures[future]

            try:
                first_stage_results[
                    (event_index, fetch_kind)
                ] = future.result()
            except Exception:
                logging.exception(
                    "Failed fetching %s for event_id=%s, name=%s.",
                    fetch_kind,
                    event_id,
                    event_name,
                )
                raise

        # -----------------------------------------------------
        # Determine event-time IDs from first-stage resources.
        # -----------------------------------------------------

        for event_index, event in enumerate(event_chunk):
            attendance_types = first_stage_results.get(
                (event_index, "attendance_types"),
                [],
            )

            period_resources = first_stage_results.get(
                (event_index, "periods"),
                [],
            )

            event_checkin_payload = first_stage_results.get(
                (event_index, "checkins"),
                [],
            )

            event_resources: list[dict[str, Any]] = [event]
            event_resources.extend(attendance_types)
            event_resources.extend(period_resources)
            event_resources.extend(event_checkin_payload)

            event_resource_blocks[event_index] = event_resources
            event_checkin_payloads[event_index] = event_checkin_payload

            temporary_index = index_resources(event_resources)

            event_time_ids: set[str] = set()

            for resource in temporary_index.values():
                if resource.get("type") == "EventTime":
                    event_time_ids.add(str(resource["id"]))

            for resource in temporary_index.values():
                if resource.get("type") != "CheckInTime":
                    continue

                event_time_id = rel_id(resource, "event_time")

                if event_time_id:
                    event_time_ids.add(str(event_time_id))

            event_time_ids_by_event_index[event_index] = event_time_ids

        # The first-stage future/result dictionaries are no longer
        # needed before second-stage requests begin.
        first_stage_futures.clear()
        first_stage_results.clear()

        # -----------------------------------------------------
        # Second stage:
        # headcounts and location event times.
        # -----------------------------------------------------

        second_stage_futures = {}

        for event_index, event in enumerate(event_chunk):
            event_id = str(event["id"])
            event_name = attrs(event).get("name") or "Unnamed event"

            event_time_ids = event_time_ids_by_event_index[event_index]

            for event_time_id in sorted(
                event_time_ids,
                key=lambda value: (
                    0,
                    int(value),
                ) if value.isdigit() else (
                    1,
                    value,
                ),
            ):
                headcounts_future = executor.submit(
                    threaded_fetch_event_time_headcounts,
                    config,
                    event_time_id,
                )

                location_event_times_future = executor.submit(
                    threaded_fetch_location_event_times,
                    config,
                    event_time_id,
                )

                second_stage_futures[headcounts_future] = (
                    event_index,
                    event_id,
                    event_name,
                    event_time_id,
                    "headcounts",
                )

                second_stage_futures[location_event_times_future] = (
                    event_index,
                    event_id,
                    event_name,
                    event_time_id,
                    "location_event_times",
                )

        second_stage_results: dict[
            tuple[int, str, str],
            list[dict[str, Any]],
        ] = {}

        for future in as_completed(second_stage_futures):
            (
                event_index,
                event_id,
                event_name,
                event_time_id,
                fetch_kind,
            ) = second_stage_futures[future]

            try:
                second_stage_results[
                    (
                        event_index,
                        event_time_id,
                        fetch_kind,
                    )
                ] = future.result()

            except PCOError as exc:
                if fetch_kind in {
                    "headcounts",
                    "location_event_times",
                }:
                    logging.warning(
                        "Failed fetching %s for event_id=%s, "
                        "event_time_id=%s: %s",
                        fetch_kind,
                        event_id,
                        event_time_id,
                        exc,
                    )

                    second_stage_results[
                        (
                            event_index,
                            event_time_id,
                            fetch_kind,
                        )
                    ] = []
                else:
                    raise

    # ---------------------------------------------------------
    # Assemble the resources for this event chunk only.
    # ---------------------------------------------------------

    for event_index, event in enumerate(event_chunk):
        event_resources = event_resource_blocks[event_index]
        event_checkin_payload = event_checkin_payloads[event_index]

        checkin_resources.extend(
            resource
            for resource in event_checkin_payload
            if resource.get("type") == "CheckIn"
        )

        event_time_ids = event_time_ids_by_event_index[event_index]

        for event_time_id in sorted(
            event_time_ids,
            key=lambda value: (
                0,
                int(value),
            ) if value.isdigit() else (
                1,
                value,
            ),
        ):
            event_resources.extend(
                second_stage_results.get(
                    (
                        event_index,
                        event_time_id,
                        "headcounts",
                    ),
                    [],
                )
            )

            event_resources.extend(
                second_stage_results.get(
                    (
                        event_index,
                        event_time_id,
                        "location_event_times",
                    ),
                    [],
                )
            )

        all_resources.extend(event_resources)

    return all_resources, checkin_resources


def iter_api_event_chunks(
    config: Config,
    event_fetch_size: int,
) -> Iterator[
    tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]
]:
    if event_fetch_size <= 0:
        raise ValueError("event_fetch_size must be greater than zero.")

    client = PCOClient(
        config.app_id,
        config.secret,
    )

    events = fetch_events(client, config)

    logging.info("Fetched %d events.", len(events))
    logging.info("Using %d worker threads.", config.max_workers)
    logging.info(
        "Processing events in chunks of %d.",
        event_fetch_size,
    )

    for chunk_number, event_chunk in enumerate(
        iter_list_chunks(events, event_fetch_size),
        start=1,
    ):
        logging.info(
            "Fetching event chunk %d with %d events.",
            chunk_number,
            len(event_chunk),
        )

        all_resources, checkin_resources = fetch_event_chunk_api_data(
            config=config,
            event_chunk=event_chunk,
        )

        yield (
            event_chunk,
            all_resources,
            checkin_resources,
        )

        all_resources.clear()
        checkin_resources.clear()
        event_chunk.clear()

        del all_resources
        del checkin_resources
        del event_chunk

        gc.collect()

    events.clear()
    del events

    gc.collect()


def iter_extraction_chunks(
    *,
    batch_size: int = 2000,
    event_fetch_size: int = 10,
) -> Iterator[dict[str, list[dict[str, Any]]]]:
    """
    Fetches, builds, and yields Check-Ins data in bounded chunks.

    batch_size:
        Maximum number of rows emitted to the uploader at once.

    event_fetch_size:
        Maximum number of events whose API resources are held in
        memory simultaneously.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero.")

    if event_fetch_size <= 0:
        raise ValueError("event_fetch_size must be greater than zero.")

    config = load_config()

    for event_chunk_number, (
        event_chunk,
        all_resources,
        checkin_resources,
    ) in enumerate(
        iter_api_event_chunks(
            config=config,
            event_fetch_size=event_fetch_size,
        ),
        start=1,
    ):
        logging.info(
            "Building rows for event chunk %d.",
            event_chunk_number,
        )

        resource_index = index_resources(all_resources)

        indexed_events = [
            resource_index[("Event", str(event["id"]))]
            for event in event_chunk
            if ("Event", str(event["id"])) in resource_index
        ]

        checkins = [
            resource
            for resource in checkin_resources
            if resource.get("type") == "CheckIn"
        ]

        convert_output_datetimes_to_local_sql(indexed_events)
        convert_output_datetimes_to_local_sql(resource_index)
        convert_output_datetimes_to_local_sql(checkins)

        # Build and completely upload each table for this event
        # chunk before building the next table.
        yield from emit_table_chunks(
            table_name="checkins_events",
            rows=build_checkin_event_rows(
                events=indexed_events,
            ),
            batch_size=batch_size,
        )

        yield from emit_table_chunks(
            table_name="checkins_event_instances",
            rows=build_checkin_event_instance_rows(
                index=resource_index,
                config=config,
            ),
            batch_size=batch_size,
        )

        yield from emit_table_chunks(
            table_name="checkins_attendance",
            rows=build_checkin_event_attendance_rows(
                checkins=checkins,
                index=resource_index,
                config=config,
            ),
            batch_size=batch_size,
        )

        yield from emit_table_chunks(
            table_name="checkins_eventtimes",
            rows=build_event_time_rows(
                index=resource_index,
                config=config,
            ),
            batch_size=batch_size,
        )

        yield from emit_table_chunks(
            table_name="headcounts",
            rows=build_headcount_rows(
                index=resource_index,
                config=config,
            ),
            batch_size=batch_size,
        )

        resource_index.clear()
        indexed_events.clear()
        checkins.clear()

        del resource_index
        del indexed_events
        del checkins

        gc.collect()

        logging.info(
            "Finished event chunk %d.",
            event_chunk_number,
        )

    logging.info("Finished Check-Ins streamed extraction.")


def extraction() -> dict[str, list[dict[str, Any]]]:
    """
    Local testing compatibility function only.

    This collects every streamed chunk into memory and therefore
    should not be used by the Azure Function orchestrator.
    """
    collected: dict[str, list[dict[str, Any]]] = {}

    for table_batch in iter_extraction_chunks(
        batch_size=2000,
        event_fetch_size=10,
    ):
        for table_name, rows in table_batch.items():
            collected.setdefault(table_name, []).extend(rows)

    return collected

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        for table_batch in iter_extraction_chunks(
            batch_size=2000,
            event_fetch_size=10,
        ):
            for table_name, rows in table_batch.items():
                logging.info(
                    "Generated table='%s', rows=%d.",
                    table_name,
                    len(rows),
                )

                rows.clear()

            table_batch.clear()

    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130)

    except Exception as exc:
        logging.exception("Check-Ins extraction failed.")
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

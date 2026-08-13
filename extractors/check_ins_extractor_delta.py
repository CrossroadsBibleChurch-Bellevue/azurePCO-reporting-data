#!/usr/bin/env python3

from __future__ import annotations

import re
import os
import sys
from collections import defaultdict
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Any, Iterable
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading


from dateutil.parser import isoparse

from utils.time_functions import convert_output_datetimes_to_local_sql
from utils.check_ins_shared import PCOError, Config, PCOClient, attrs, rel_id
from extractors.builders.check_ins_builders import build_checkin_event_attendance_rows, build_checkin_event_instance_rows, build_checkin_event_rows, build_event_time_rows, build_headcount_rows
from extractors.fetchers.check_ins_fetchers import fetch_events, fetch_attendance_types, fetch_event_checkins, fetch_event_periods, fetch_event_time_headcounts, fetch_event_times_delta, fetch_location_event_times
from database.fetch_record import fetch_updated_at_checkins


updated_at_filter = fetch_updated_at_checkins()

load_dotenv()

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
        checkin_updated_since=parse_datetime_env(updated_at_filter),
        event_time_updated_since=parse_datetime_env(updated_at_filter),
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



def threaded_fetch_attendance_types(config: Config, event_id: str) -> list[dict[str, Any]]:
    return fetch_attendance_types(get_thread_client(config), event_id)


def threaded_fetch_event_periods(config: Config, event_id: str) -> list[dict[str, Any]]:
    return fetch_event_periods(get_thread_client(config), event_id)


def threaded_fetch_event_checkins(config: Config, event_id: str,) -> list[dict[str, Any]]:
    return fetch_event_checkins(get_thread_client(config), config, event_id)


def threaded_fetch_event_time_headcounts(config: Config, event_time_id: str) -> list[dict[str, Any]]:
    return fetch_event_time_headcounts(get_thread_client(config), event_time_id)


def threaded_fetch_location_event_times(config: Config, event_time_id: str) -> list[dict[str, Any]]:
    return fetch_location_event_times(get_thread_client(config), event_time_id)


def fetch_all_api_data(
    config: Config,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    client = PCOClient(config.app_id, config.secret)

    all_resources: list[dict[str, Any]] = []
    checkin_resources: list[dict[str, Any]] = []

    events = fetch_events(client, config)
    event_time_delta_resources = fetch_event_times_delta(
        client,
        config,
    )

    delta_event_times = [
        resource
        for resource in event_time_delta_resources
        if resource.get("type") == "EventTime"
    ]

    # Index EventPeriod resources included in the EventTime delta response.
    delta_event_periods_by_id: dict[str, dict[str, Any]] = {
        str(resource["id"]): resource
        for resource in event_time_delta_resources
        if resource.get("type") == "EventPeriod"
        and resource.get("id") is not None
    }

    # Group delta EventTime resources and their IDs by Check-In Event ID.
    delta_event_times_by_event_id: dict[
        str,
        list[dict[str, Any]],
    ] = defaultdict(list)

    delta_event_time_ids_by_event_id: dict[
        str,
        set[str],
    ] = defaultdict(set)

    for event_time in delta_event_times:
        event_time_id = str(event_time["id"])

        # EventTime normally provides a direct event relationship.
        event_id = rel_id(event_time, "event")

        # Fall back through the related EventPeriod if needed.
        if not event_id:
            event_period_id = rel_id(
                event_time,
                "event_period",
            )

            event_period = (
                delta_event_periods_by_id.get(event_period_id)
                if event_period_id
                else None
            )

            event_id = rel_id(
                event_period,
                "event",
            )

        if not event_id:
            continue

        delta_event_times_by_event_id[event_id].append(
            event_time
        )

        delta_event_time_ids_by_event_id[event_id].add(
            event_time_id
        )

    event_resource_blocks: dict[int, list[dict[str, Any]]] = {}
    event_checkin_payloads: dict[int, list[dict[str, Any]]] = {}
    event_time_ids_by_event_index: dict[int, set[str]] = {}

    with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
        first_stage_futures = {}

        for event_index, event in enumerate(events):
            event_id = str(event["id"])
            event_name = attrs(event).get("name") or "Unnamed event"

            attendance_future = executor.submit(threaded_fetch_attendance_types, config, event_id)
            periods_future = executor.submit(threaded_fetch_event_periods, config, event_id)
            checkins_future = executor.submit(threaded_fetch_event_checkins, config, event_id)

            first_stage_futures[attendance_future] = (event_index, event_id, event_name, "attendance_types")
            first_stage_futures[periods_future] = (event_index, event_id, event_name, "periods")
            first_stage_futures[checkins_future] = (event_index, event_id, event_name, "checkins")

        first_stage_results: dict[tuple[int, str], list[dict[str, Any]]] = {}


        for future in as_completed(first_stage_futures):
            event_index, event_id, event_name, fetch_kind = first_stage_futures[future]

            try:
                result = future.result()
                first_stage_results[(event_index, fetch_kind)] = result
            except Exception as exc:
                print(
                    f"ERROR while fetching {fetch_kind} for event_id={event_id}, "
                    f"name={event_name}: {exc}"
                )
                raise


        second_stage_futures = {}

        for event_index, event in enumerate(events):
            event_id = str(event["id"])
            event_name = attrs(event).get("name") or "Unnamed event"

            attendance_types = first_stage_results[(event_index, "attendance_types")]
            period_resources = first_stage_results[(event_index, "periods")]
            event_checkin_payload = first_stage_results[(event_index, "checkins")]

            event_resources: list[dict[str, Any]] = [event]
            event_resources.extend(attendance_types)
            event_resources.extend(period_resources)
            event_resources.extend(event_checkin_payload)

            # Add only EventTime resources returned by the delta request
            # that belong to the current event.
            delta_event_times_for_event = (
                delta_event_times_by_event_id.get(
                    event_id,
                    [],
                )
            )

            event_resources.extend(delta_event_times_for_event)

            # Add any included EventPeriod resources needed by the delta
            # EventTimes. index_resources() later removes duplicate resources.
            for event_time in delta_event_times_for_event:
                event_period_id = rel_id(
                    event_time,
                    "event_period",
                )

                if not event_period_id:
                    continue

                delta_event_period = delta_event_periods_by_id.get(
                    event_period_id
                )

                if delta_event_period:
                    event_resources.append(delta_event_period)

            event_resource_blocks[event_index] = event_resources
            event_checkin_payloads[event_index] = event_checkin_payload

            # Only process EventTimes returned by the delta EventTime request.
            # Do not add EventTime IDs discovered through changed CheckIns,
            # because those EventTimes may be older than the delta cutoff.
            event_time_ids: set[str] = set(
                delta_event_time_ids_by_event_id.get(
                    event_id,
                    set(),
                )
            )


            event_time_ids_by_event_index[event_index] = event_time_ids

            for event_time_id in sorted(event_time_ids, key=lambda x: int(x) if x.isdigit() else x):
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


        second_stage_results: dict[tuple[int, str, str], list[dict[str, Any]]] = {}

        for future in as_completed(second_stage_futures):
            event_index, event_id, event_name, event_time_id, fetch_kind = second_stage_futures[future]

            try:
                result = future.result()
                second_stage_results[(event_index, event_time_id, fetch_kind)] = result
            except PCOError as exc:
                if fetch_kind == "headcounts":
                    print(
                        f"WARNING: failed headcounts for "
                        f"event_id={event_id}, event_time_id={event_time_id}: {exc}"
                    )
                elif fetch_kind == "location_event_times":
                    print(
                        f"WARNING: failed location_event_times for "
                        f"event_id={event_id}, event_time_id={event_time_id}: {exc}"
                    )
                else:
                    raise


    for event_index, event in enumerate(events):
        event_resources = event_resource_blocks[event_index]

        event_checkin_payload = event_checkin_payloads[event_index]
        event_checkins = [r for r in event_checkin_payload if r.get("type") == "CheckIn"]
        checkin_resources.extend(event_checkins)

        event_time_ids = event_time_ids_by_event_index[event_index]

        for event_time_id in sorted(event_time_ids, key=lambda x: int(x) if x.isdigit() else x):
            event_resources.extend(
                second_stage_results.get((event_index, event_time_id, "headcounts"), [])
            )
            event_resources.extend(
                second_stage_results.get((event_index, event_time_id, "location_event_times"), [])
            )

        all_resources.extend(event_resources)

        event_id = str(event["id"])

    return events, all_resources, checkin_resources



def extraction() -> dict[str, list[dict[str, Any]]]:
    config = load_config()

    events, all_resources, checkin_resources = fetch_all_api_data(config)

    index = index_resources(all_resources)
    events = [index[("Event", str(e["id"]))] for e in events if ("Event", str(e["id"])) in index]
    checkins = [r for r in checkin_resources if r.get("type") == "CheckIn"]

    convert_output_datetimes_to_local_sql(events)
    convert_output_datetimes_to_local_sql(index)
    convert_output_datetimes_to_local_sql(checkins)

    checkin_event_rows = build_checkin_event_rows(
        events=events,
    )

    checkin_event_instance_rows = build_checkin_event_instance_rows(
        index=index,
        config=config,
    )

    checkin_event_attendance_rows = build_checkin_event_attendance_rows(
        checkins=checkins,
        index=index,
        config=config,
    )

    headcount_rows = build_headcount_rows(
        index=index,
        config=config,
    )

    event_time_rows = build_event_time_rows(
        index=index,
        config=config,
    )

    return {
        "checkins_events": list(checkin_event_rows),
        "checkins_event_instances": list(checkin_event_instance_rows),
        "checkins_attendance": list(checkin_event_attendance_rows),
        "checkins_eventtimes": list(event_time_rows),
        "headcounts": list(headcount_rows)
    }

def main():
    try:
        raise SystemExit(extraction())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

if __name__ == "__main__":
    main()
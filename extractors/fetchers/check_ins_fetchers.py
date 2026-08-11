from typing import Any

from utils.time_functions import format_api_datetime
from utils.check_ins_shared import PCOClient, Config

def fetch_events(client: PCOClient, config: Config) -> list[dict[str, Any]]:
    if config.event_id:
        payload = client.get_json(f"events/{config.event_id}", params={"include": "attendance_types"})
        resources = [payload["data"]] + (payload.get("included") or [])
        return [r for r in resources if r.get("type") == "Event"]

    resources = client.get_collection_payloads(
        "events",
        params={
            "include": "attendance_types",
            "order": "name",
        },
    )
    events = [r for r in resources if r.get("type") == "Event"]

    if config.max_events is not None:
        events = events[: config.max_events]

    return events


def fetch_event_periods(
    client: PCOClient,
    event_id: str,
) -> list[dict[str, Any]]:
    return client.get_collection_payloads(
        f"events/{event_id}/event_periods",
        params={
            "include": "event",
            "order": "-starts_at",
        },
    )

def fetch_event_times_delta(
    client: PCOClient,
    config: Config,
) -> list[dict[str, Any]]:
    """
    Fetch EventTime resources updated on or after the configured timestamp.

    API request:
        GET /check-ins/v2/event_times
        ?where[updated_at][gte]=2026-08-01T19:51:51Z
        &include=event,event_period
    """
    return client.get_collection_payloads(
        "event_times",
        params={
            "where[updated_at][gte]": format_api_datetime(
                config.event_time_updated_since
            ),
            "include": "event,event_period",
        },
    )


def fetch_event_checkins(
    client: PCOClient,
    config: Config,
    event_id: str,
) -> list[dict[str, Any]]:
    return client.paginate_updated_since(
        path=f"events/{event_id}/check_ins",
        updated_since=config.checkin_updated_since,
        params={
            "include": (
                "person,event,event_period,check_in_times,locations"
            ),
            "order": "-updated_at",
        },
    )


def fetch_attendance_types(client: PCOClient, event_id: str) -> list[dict[str, Any]]:
    return client.get_collection_payloads(f"events/{event_id}/attendance_types")


def fetch_event_time_headcounts(client: PCOClient, event_time_id: str) -> list[dict[str, Any]]:
    return client.get_collection_payloads(
        f"event_times/{event_time_id}/headcounts",
        params={"include": "attendance_type,event_time"},
    )


def fetch_location_event_times(client: PCOClient, event_time_id: str) -> list[dict[str, Any]]:
    return client.get_collection_payloads(
        f"event_times/{event_time_id}/location_event_times",
        params={"include": "event_time,location"},
    )
from typing import Any, Dict, Tuple, Optional, List
from datetime import timedelta, datetime, timezone
from zoneinfo import ZoneInfo

from extractors.api_fetcher import pco_get_all_pages, pco_get
from utils.response_parsers import safe_get
from extractors.schemas.calendar_schemas import build_row

# Fetch next 7 days of event instances, from time program is run till 7 days from then
# Gets events, owners, event tags, event times, resource bookings, instance tags, resource bookings, and resource requests
def fetch_event_instances_next_7_days(auth: Tuple[str, str], tz: ZoneInfo) -> Dict[str, Any]:
    # Calculate start and end time, can change the delta in now_local to fetch days prior as well
    now_current = datetime.now(tz)
    now_local = now_current - timedelta(days=1)
    end_local = now_current + timedelta(days=7)

    # Calculate time change
    now_utc = now_local.astimezone(timezone.utc).replace(microsecond=0)
    end_utc = end_local.astimezone(timezone.utc).replace(microsecond=0)

    # All the includes in the API request
    include = ",".join([
        "event",
        "event.owner",
        "event.tags",
        "event_times",
        "resource_bookings",
        "tags",
        "resource_bookings.resource",
        "resource_bookings.event_resource_request",
    ])

    # Parameters used in API call, ordered by when the event starts
    params = {
        "include": include,
        "order": "starts_at",
        "where[starts_at][lt]": end_utc.isoformat().replace("+00:00", "Z"),
        "where[ends_at][gte]": now_utc.isoformat().replace("+00:00", "Z"),
    }

    # Fetch the data, page by page, 100 at a time
    return pco_get_all_pages("/calendar/v2/event_instances", auth, params=params, per_page=100)

def fetch_tag_groups_with_tags(auth: Tuple[str, str]) -> Dict[str, Any]:
    # Tag groups + their tags so we can build:
    # - tag_groups
    # - tag_groups_tag_maps (tag <-> group bridge)
    params = {"include": "tags", "order": "name"}
    return pco_get_all_pages("/calendar/v2/tag_groups", auth, params=params, per_page=100)


def fetch_room(auth: Tuple[str, str], room_id: str) -> Dict[str, Any]:
    # Rooms are separate from resources in PCO Calendar API
    return pco_get(f"/calendar/v2/rooms/{room_id}", auth, params=None)
# Simple function that gets event resource request data with includes to increase data fetched
def fetch_event_resource_request(auth: Tuple[str, str], req_id: str) -> Dict[str, Any]:
    params = {"include": "room_setup,resource,created_by,updated_by,event"}
    return pco_get(f"/calendar/v2/event_resource_requests/{req_id}", auth, params=params)


# Simple function that gets event resource questions
def fetch_resource_with_questions(auth: Tuple[str, str], resource_id: str) -> Dict[str, Any]:
    return pco_get(f"/calendar/v2/resources/{resource_id}", auth, params={"include": "resource_questions"})

# Function that gets event resource answers given a resource request ID, if not then raises error
def fetch_event_resource_answers_for_request(auth: Tuple[str, str], req_id: str) -> Dict[str, Any]:
    attempts: List[Tuple[str, Optional[Dict[str, str]]]] = [
        (f"/calendar/v2/event_resource_requests/{req_id}/answers", None),
    ]

    errors: List[str] = []
    for path, params in attempts:
        try:
            return pco_get(path, auth, params=params)
        except RuntimeError as e:
            errors.append(str(e))

    raise RuntimeError(
        "Unable to fetch event resource answers for request_id={}\nTried:\n{}\n\nErrors:\n{}".format(
            req_id,
            "\n".join([f"  - {p} {params or ''}".rstrip() for (p, params) in attempts]),
            "\n\n".join(errors),
        )
    )

# Function that given group ID, fetches the members in it, this is used to get the staff members, who are people that create calendar events
def fetch_group_members_owner_table(auth: Tuple[str, str], group_id: str) -> List[Dict[str, Any]]:
    url = f"https://api.planningcenteronline.com/groups/v2/groups/{group_id}/memberships"

    params = {
        "include": "person",
        "per_page": 100
    }

    all_members = []
    offset = 0

    while True:
        params["offset"] = offset

        payload = pco_get("", auth, params={**params, "url_override": url})

        memberships = payload.get("data", [])
        included = payload.get("included", [])

        people_map = {
            p["id"]: p for p in included if p["type"] == "Person"
        }

        for m in memberships:
            person_id = safe_get(m, "relationships", "person", "data", "id")

            if not person_id:
                continue

            person = people_map.get(person_id, {})
            attr = person.get("attributes", {})

            all_members.append(build_row("owners", {
                "owner_id": person_id,
                "owner_attr": attr
            }))

        if len(memberships) < 100:
            break

        offset += 100

    return all_members
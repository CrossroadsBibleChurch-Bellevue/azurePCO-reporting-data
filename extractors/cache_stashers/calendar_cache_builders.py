from typing import Tuple, Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from utils.response_parsers import index_included, safe_get
from extractors.fetchers.calendar_fetchers import fetch_event_resource_request, fetch_room, fetch_resource_with_questions, fetch_event_resource_answers_for_request

def build_rooms_cache(auth: Tuple[str, str], room_ids: List[str], max_workers: int) -> Dict[str, Dict[str, Any]]:
    unique = sorted(set([r for r in room_ids if r]))
    cache: Dict[str, Dict[str, Any]] = {}

    def fetch_one(rid: str) -> Tuple[str, Dict[str, Any]]:
        payload = fetch_room(auth, rid)
        return rid, payload.get("data") or {}

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(fetch_one, rid) for rid in unique]
        for fut in as_completed(futures):
            rid, obj = fut.result()
            cache[rid] = obj

    return cache


# From resource request IDs, seek to get more data from those IDs, such as room setup, event, etc.
def enrich_requests(auth: Tuple[str, str], req_ids: List[str], max_workers: int) -> Dict[str, Dict[str, Any]]:
    # Get only unique request IDs and sort them, from smallest to largest
    unique = sorted(set([r for r in req_ids if r]))
    # Build cache that will hold JSON responses
    cache: Dict[str, Dict[str, Any]] = {}

    # Function that given request ID will fetch more data and parse it out into appropriate segments
    def enrich_one(rid: str) -> Tuple[str, Dict[str, Any]]:
        # Fetch more data
        payload = fetch_event_resource_request(auth, rid)
        # Seperate includes and data section of JSON response
        data = payload.get("data", {}) or {}
        included = payload.get("included", []) or []
        # Clean up includes data to get ID and type and use that as the key for the included section of data
        inc = index_included(included)
        # Get the relationships chunk, which will be used later to get other data easier
        rel = data.get("relationships", {}) or {}

        # Function that given key in relationship chunk, will get the corresponding data for the key
        def resolve_one(rel_name: str) -> Optional[Dict[str, Any]]:
            ref = safe_get(rel, rel_name, "data", default=None)
            if isinstance(ref, dict) and ref.get("type") and ref.get("id"):
                return inc.get((ref["type"], ref["id"]))
            return None

        # Return data with the resource ID
        return rid, {
            "request": data,
            "resource": resolve_one("resource"),
            "room_setup": resolve_one("room_setup"),
            "created_by": resolve_one("created_by"),
            "updated_by": resolve_one("updated_by"),
            "event": resolve_one("event"),
        }

    # Multi-thread getting data and enriching it, since only one request ID per API call is allowed
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(enrich_one, rid) for rid in unique]
        for fut in as_completed(futures):
            rid, blob = fut.result()
            cache[rid] = blob

    return cache


# Function that is similar to enrich_requests, but gets the resource request questions, multi-threaded
def build_resource_questions_cache(auth: Tuple[str, str], resource_ids: List[str], max_workers: int) -> Dict[str, Dict[str, Any]]:
    unique = sorted(set([r for r in resource_ids if r]))
    cache: Dict[str, Dict[str, Any]] = {}

    def fetch_one(rid: str) -> Tuple[str, Dict[str, Any]]:
        payload = fetch_resource_with_questions(auth, rid)
        data = payload.get("data") or {}
        included = payload.get("included") or []
        return rid, {
            "resource": data,
            "included_index": index_included(included),
            "included_raw": included,
        }

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(fetch_one, rid) for rid in unique]
        for fut in as_completed(futures):
            rid, blob = fut.result()
            cache[rid] = blob

    return cache

# Similar function to the enrich_requests, except gets event resource request answers, multi-threaded
def fetch_answers_cache(auth: Tuple[str, str], req_ids: List[str], max_workers: int) -> Dict[str, Dict[str, Any]]:
    # Get only the unique IDs and sort them
    unique = sorted(set([r for r in req_ids if r]))
    out: Dict[str, Dict[str, Any]] = {}

    def fetch_one(rid: str) -> Tuple[str, Dict[str, Any]]:
        return rid, fetch_event_resource_answers_for_request(auth, rid)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(fetch_one, rid) for rid in unique]
        for fut in as_completed(futures):
            rid, payload = fut.result()
            out[rid] = payload

    return out
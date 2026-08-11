#!/usr/bin/env python3
import os
import time
import logging
from typing import Dict, Any, List
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor

from utils.metering import AzureLikeExecutionMeter
from utils.response_parsers import _first_present, index_included, safe_get
from utils.datatable_helpers import upsert_row
from extractors.schemas.calendar_schemas import build_row_calendar
from utils.env_fetcher import get_auth_from_env
from utils.time_functions import to_local, parse_iso
from extractors.fetchers.calendar_fetchers import fetch_event_instances_next_7_days, fetch_group_members_owner_table, fetch_tag_groups_with_tags
from extractors.cache_stashers.calendar_cache_builders import enrich_requests, fetch_answers_cache, build_resource_questions_cache, build_rooms_cache


# Big function that goes through the data and builds tables that will be used in dataverse
def build_relational_tables(
    payload: Dict[str, Any],
    tz: ZoneInfo,
    req_cache: Dict[str, Dict[str, Any]],
    resource_q_cache: Dict[str, Dict[str, Any]],
    answers_cache: Dict[str, Dict[str, Any]],
    rooms_cache: Dict[str, Dict[str, Any]],
    tag_groups_payload: Dict[str, Any],
    owners_rows: Dict[str, Any],
) -> Dict[str, Any]:
    # Get the data and included section from the JSON response and index the includes section
    data = payload.get("data", []) or []
    included = payload.get("included", []) or []
    inc = index_included(included)

    # all the tables that will be in dataverse
    owners: Dict[str, Dict[str, Any]] = {}
    events: Dict[str, Dict[str, Any]] = {}
    event_instances: Dict[str, Dict[str, Any]] = {}
    event_times: Dict[str, Dict[str, Any]] = {}
    event_resource_requests: Dict[str, Dict[str, Any]] = {}
    event_resource_answers: Dict[str, Dict[str, Any]] = {}
    resource_bookings: Dict[str, Dict[str, Any]] = {}
    resources: Dict[str, Dict[str, Any]] = {}
    rooms: Dict[str, Dict[str, Any]] = {}
    room_setups: Dict[str, Dict[str, Any]] = {}
    tags: Dict[str, Dict[str, Any]] = {}
    tag_groups: Dict[str, Dict[str, Any]] = {}
    tag_groups_tag_maps: Dict[str, Dict[str, Any]] = {}
    event_instance_tag_map: Dict[str, Dict[str, Any]] = {}
    schedule: List[Dict[str, Any]] = []

    # List to ensure no duplicate schedule entries are created for resource booking ID (i.e. no two schedule entries for resource booking ID 4829582 or whatever it might be)
    rb_id_list = []

    # Create the tag groups table and tag table, and tag group tag map table
    # Get tag group data and includes from the payload and index it
    tg_data = (tag_groups_payload or {}).get("data", []) or []
    tg_inc = index_included((tag_groups_payload or {}).get("included", []) or [])

    # Step through all tag data, getting ID, attributes, relationships, and then upsert into the dictionary
    # For each table we create a unique ID with the table ID, so for tag groups, it is the tag group ID and the string "tag_group" computed to make a hash, ensuring no duplicates
    for tg in tg_data:
        tg_id = tg.get("id")
        tg_attr = tg.get("attributes", {}) or {}
        tg_rel = tg.get("relationships", {}) or {}

        if tg_id:
            upsert_row(tag_groups, build_row_calendar("tag_groups", {
                "tg_id": tg_id,
                "tg_attr": tg_attr,
            }), pk="cr548_id")

        # Next get tags, which have names, colors and such, they are things like "Men's Ministy" or "Youth Ministry"
        tg_tag_refs = safe_get(tg_rel, "tags", "data", default=[]) or []
        for tr in tg_tag_refs:
            tag_id = tr.get("id")
            if not tg_id or not tag_id:
                continue

            t_obj = tg_inc.get((tr.get("type"), tag_id), {}) or {}
            t_attr = t_obj.get("attributes", {}) or {}
            upsert_row(tags, build_row_calendar("tags", {
                    "tag_id": tag_id,
                    "t_attr": t_attr,
                }), pk="cr548_id")
            
            # Create a sort of bridge between tags and tag groups
            upsert_row(tag_groups_tag_maps, build_row_calendar("tag_groups_tag_maps", {
                "tag_id": tag_id,
                "tg_id": tg_id,
            }), pk="unique_id")

    # Parse through resource data and if it is not a room, then add it to the resource table
    for resource_id, blob in (resource_q_cache or {}).items():
        res_obj = blob.get("resource") or {}
        res_attr = res_obj.get("attributes", {}) or {}
        if not resource_id:
            continue
        
        if res_attr.get("kind") != "Room":
            upsert_row(resources, build_row_calendar("resources", {
                "resource_id": resource_id,
                "res_attr": res_attr
            }), pk="cr548_id")

    # Next get and upsert data into the rooms table
    for room_id, room_obj in (rooms_cache or {}).items():
        r_attr = (room_obj or {}).get("attributes", {}) or {}
        if not room_id:
            continue

        upsert_row(rooms, build_row_calendar("rooms", {
            "room_id": room_id,
            "r_attr": r_attr
        }), pk="cr548_id")

    # From the event instances API call, and other calls, form owners, events, event instances, and all the remaining tables, as well as add to existing tables
    # This steps through the data to ensure all of it is processed and used
    for inst in data:
        inst_id = inst.get("id")
        attr = inst.get("attributes", {}) or {}
        rel = inst.get("relationships", {}) or {}

        # Event
        ev_ref = safe_get(rel, "event", "data", default={}) or {}
        ev_id = ev_ref.get("id")
        ev = inc.get((ev_ref.get("type"), ev_id), {}) if ev_id else {}
        ev_attr = ev.get("attributes", {}) or {}
        ev_rel = ev.get("relationships", {}) or {}

        # Owners table
        owner_ref = safe_get(ev_rel, "owner", "data", default=None)
        owner_id = owner_ref.get("id") if isinstance(owner_ref, dict) else None
        if owner_id:
            owner_obj = inc.get((owner_ref.get("type"), owner_id), {}) or {}
            owner_attr = owner_obj.get("attributes", {}) or {}
            upsert_row(owners, build_row_calendar("owners", {
                "owner_id": owner_id,
                "owner_attr": owner_attr
            }), pk="cr548_id")

        # Events table
        if ev_id:
            if owner_id == "null_person":
                owner_id = None
            upsert_row(events, build_row_calendar("events", {
                "ev_id": ev_id,
                "ev_attr": ev_attr,
                "owner_id": owner_id,
            }), pk="cr548_id")

        # Tags table from event tags relationship
        ev_tag_refs = safe_get(ev_rel, "tags", "data", default=[]) or []
        for tr in ev_tag_refs:
            tag_id = tr.get("id")
            if not tag_id:
                continue
            t_obj = inc.get((tr.get("type"), tag_id), {}) or {}
            t_attr = t_obj.get("attributes", {}) or {}
            upsert_row(tags, build_row_calendar("tags", {
                    "tag_id": tag_id,
                    "t_attr": t_attr,
                }), pk="cr548_id")

        # EventInstances table
        starts_local = to_local(parse_iso(attr.get("starts_at")), tz)
        day_of_week = starts_local.isoweekday() if starts_local else None

        upsert_row(event_instances, build_row_calendar("event_instances", {
            "inst_id": inst_id,
            "ev_id": ev_id,
            "attr": attr,
            "day_of_week": day_of_week,
        }), pk="cr548_id")

        # EventTimes table
        et_refs = safe_get(rel, "event_times", "data", default=[]) or []
        for r in et_refs:
            et_id = r.get("id")
            if not et_id:
                continue
            et_obj = inc.get((r.get("type"), et_id), {}) or {}
            et_attr = et_obj.get("attributes", {}) or {}
            upsert_row(event_times, build_row_calendar("event_times", {
                "et_id": et_id,
                "ev_id": ev_id,
                "et_attr": et_attr
            }), pk="cr548_id")

        # Instance-level tags
        inst_tag_refs = safe_get(rel, "tags", "data", default=[]) or []
        for tr in inst_tag_refs:
            tag_id = tr.get("id")
            if not tag_id or not inst_id:
                continue
            t_obj = inc.get((tr.get("type"), tag_id), {}) or {}
            t_attr = t_obj.get("attributes", {}) or {}
            upsert_row(tags, build_row_calendar("tags", {
                    "tag_id": tag_id,
                    "t_attr": t_attr,
                }), pk="cr548_id")
            
            # Event instance ID and tag ID bridge
            upsert_row(event_instance_tag_map, build_row_calendar("event_instance_tag_map", {
                "inst_id": inst_id,
                "tag_id": tag_id,
            }), pk="alt_key")

        # ResourceBookings
        rb_refs = safe_get(rel, "resource_bookings", "data", default=[]) or []
        for r in rb_refs:
            rb_id = r.get("id")
            if not rb_id:
                continue
            rb = inc.get((r.get("type"), rb_id), {}) or {}
            rb_attr = rb.get("attributes", {}) or {}
            rb_rel = rb.get("relationships", {}) or {}

            # resource/room
            res_ref = safe_get(rb_rel, "resource", "data", default={}) or {}
            res_id = res_ref.get("id")
            res_type = res_ref.get("type")

            if res_id and res_type:
                res_obj = inc.get((res_type, res_id), {}) or {}
                res_attr = res_obj.get("attributes", {}) or {}
                res_type = res_attr.get("kind")

                if res_type.lower() == "room":
                    upsert_row(rooms, build_row_calendar("rooms", {
                        "room_id": res_id,
                        "r_attr": res_attr
                    }), pk="cr548_id")
                else:
                    upsert_row(resources, build_row_calendar("resources", {
                        "resource_id": res_id,
                        "res_attr": res_attr
                    }), pk="cr548_id")

            # request
            req_ref = safe_get(rb_rel, "event_resource_request", "data", default=None)
            req_id = req_ref.get("id") if isinstance(req_ref, dict) else None

            # ResourceBookings row
            upsert_row(resource_bookings, build_row_calendar("resource_bookings", {
                "rb_id": rb_id,
                "ev_id": ev_id,
                "inst_id": inst_id,
                "res_id": res_id,
                "req_id": req_id,
                "rb_attr": rb_attr,
            }), pk="cr548_id")

            # If the request ID is in the resource request dictionary, use the data to upsert into room setups, event resource requests, and add to the schedule
            if req_id and req_id in req_cache:
                req_data = req_cache[req_id].get("request") or {}
                req_attr = req_data.get("attributes", {}) or {}
                req_rel = req_data.get("relationships", {}) or {}

                req_event_ref = safe_get(req_rel, "event", "data", default=None)
                req_event_id = req_event_ref.get("id") if isinstance(req_event_ref, dict) else None

                req_res_ref = safe_get(req_rel, "resource", "data", default=None)
                req_resource_id = req_res_ref.get("id") if isinstance(req_res_ref, dict) else None

                rs = req_cache[req_id].get("room_setup") or {}
                rs_id = rs.get("id")
                rs_attr = rs.get("attributes", {}) or {}

                created_by = req_cache[req_id].get("created_by") or {}
                updated_by = req_cache[req_id].get("updated_by") or {}
                created_by_id = created_by.get("id")
                updated_by_id = updated_by.get("id")

                if rs_id:
                    upsert_row(room_setups, build_row_calendar("room_setups", {
                        "rs_id": rs_id,
                        "rs_attr": rs_attr
                    }), pk="cr548_id")

                upsert_row(event_resource_requests, build_row_calendar("event_resource_requests", {
                    "req_id": req_id,
                    "req_event_id": req_event_id,
                    "req_resource_id": req_resource_id,
                    "rs_id": rs_id,
                    "req_attr": req_attr,
                    "created_by_id": created_by_id,
                    "updated_by_id": updated_by_id
                }), pk="cr548_id")

                # Get the resource question answer data
                ans_payload = (answers_cache.get(req_id) or {})
                ans_data = ans_payload.get("data", []) or []

        
                if not ans_data:
                    if res_id:
                            room = rooms.get(res_id)
                            if room is not None:
                                room_names = room.get("cr548_name1")
                                if room_names is not None:
                                    schedule.append(build_row_calendar("schedule", {
                                        "inst_id": inst_id,
                                        "ans": answer_text if answer_text is not None else "(Unanswered)",
                                        "ques": question_text,
                                        "req_id": req_id,
                                        "ev_id": ev_id,
                                        "ev_attr": ev_attr,
                                        "req_attr": req_attr,
                                        "owners": owners,
                                        "owner_id": owner_id,
                                        "rb_attr": rb_attr,
                                        "rb_id": rb_id,
                                        "res_id": req_resource_id or res_id,
                                        "rs_id": rs_id,
                                        "room_setups": room_setups,
                                        "rooms": rooms,
                                    }))

                # Step through the answer data, parse it out, and then upsert data into the event resource answer table and add to the schedule if it is not in there already
                for ans in ans_data:
                    ans_id = ans.get("id")
                    ans_attr = ans.get("attributes", {}) or {}
                    ans_rel = ans.get("relationships", {}) or {}

                    q_ref = safe_get(ans_rel, "resource_question", "data", default=None)
                    q_id = q_ref.get("id") if isinstance(q_ref, dict) else None

                    # question text if included
                    question_pre_text = ans_attr.get("question", {}) or {}
                    question_text_extended = question_pre_text.get("question", {}) or {}
                    question_text = question_text_extended[:100]

                    answer_text = _first_present(ans_attr, ["answer", "value", "response", "text"])

                    if ans_id:
                        if isinstance(answer_text, list):
                            answer_text = ", ".join(answer_text)
                        upsert_row(event_resource_answers, build_row_calendar("event_resource_answers", {
                            "ans_id": ans_id,
                            "req_id": req_id,
                            "q_id": q_id,
                            "question_text": question_text,
                            "answer_text": answer_text,
                            "ans_attr": ans_attr
                        }), pk="cr548_id")

                    # Schedule row per answer
                    if rb_id in rb_id_list:
                        continue
                    else:
                        if res_id:
                            room = rooms.get(res_id)
                            if room is not None:
                                room_names = room.get("cr548_name1")
                                if room_names is not None:
                                    schedule.append(build_row_calendar("schedule", {
                                        "inst_id": inst_id,
                                        "ans": answer_text if answer_text is not None else "(Unanswered)",
                                        "ques": question_text,
                                        "req_id": req_id,
                                        "ev_id": ev_id,
                                        "ev_attr": ev_attr,
                                        "req_attr": req_attr,
                                        "owners": owners,
                                        "owner_id": owner_id,
                                        "rb_attr": rb_attr,
                                        "rb_id": rb_id,
                                        "res_id": req_resource_id or res_id,
                                        "rs_id": rs_id,
                                        "room_setups": room_setups,
                                        "rooms": rooms,
                                    }))
                                    rb_id_list.append(rb_id)

    return {
        "event_instance_tag_map": list(event_instance_tag_map.values()),
        "event_instances": list(event_instances.values()),
        "event_resource_answers": list(event_resource_answers.values()),
        "event_resource_requests": list(event_resource_requests.values()),
        "event_times": list(event_times.values()),
        "events": list(events.values()),
        "owners": owners_rows,
        "resource_bookings": list(resource_bookings.values()),
        "resources": list(resources.values()),
        "room_setups": list(room_setups.values()),
        "rooms": list(rooms.values()),
        "schedule": schedule,
        "tag_groups_tag_maps": list(tag_groups_tag_maps.values()),
        "tag_groups": list(tag_groups.values()),
        "tags": list(tags.values()),
    }


# Function to extract tables, main one used, called by other files
def extract_tables() -> Dict[str, Any]:
    # Meter to measure how much time, memory, and GB-seconds are consumed, to estimate costs when using in Azure Functions
    with AzureLikeExecutionMeter("calendar-extraction") as m:
        # Get auth variables to fetch data from API, potentially could get multiple users keys to speed up, but might be more trouble than it is worth
        auth = get_auth_from_env()

        # Get timezone so that we get the correct time and date to fetch the next seven days of data (might be unnecessary)
        tz_name = os.getenv("PCO_TZ", "America/Los_Angeles")
        tz = ZoneInfo(tz_name)

        # Get max HTTP workers to use from environment, to multithread API requests
        max_workers = int(os.getenv("PCO_MAX_WORKERS", "12"))

        # Get event instances for the next seven days, 
        payload = fetch_event_instances_next_7_days(auth, tz)

        # Set variable types
        resource_ids_from_bookings: List[str] = []
        room_ids_from_bookings: List[str] = []
        req_ids: List[str] = []

        # Step through each part of the event instances
        for item in payload.get("included", []) or []:
            # If the event instance included type is a resource booking, then get 
            if item.get("type") == "ResourceBooking":
                # Get the values from the event resource request in the Resource Booking includes data
                req_ref = safe_get(item, "relationships", "event_resource_request", "data", default=None)
                # Ensure that an ID is present, and if it is, then append the ID to the list of request IDs
                if isinstance(req_ref, dict) and req_ref.get("id"):
                    req_ids.append(req_ref["id"])

                # Get the resource data from resource bookings, and then if it is a room, add the ID to the room ids list, else add it to the resource ids list
                res_ref = safe_get(item, "relationships", "resource", "data", default=None)
                if isinstance(res_ref, dict) and res_ref.get("id"):
                    if (res_ref.get("type") or "").lower() == "room":
                        room_ids_from_bookings.append(res_ref["id"])
                    else:
                        resource_ids_from_bookings.append(res_ref["id"])

        # Sort request, resource, and room ids
        req_ids = sorted(set([r for r in req_ids if r]))
        resource_ids_from_bookings = sorted(set([r for r in resource_ids_from_bookings if r]))
        room_ids_from_bookings = sorted(set([r for r in room_ids_from_bookings if r]))

        # Next multi-thread fetching data, resource requests, resource question answers, resource questions, and rooms
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_req_cache = ex.submit(enrich_requests, auth, req_ids, max_workers)
            f_ans_cache = ex.submit(fetch_answers_cache, auth, req_ids, max_workers)
            f_res_cache = ex.submit(build_resource_questions_cache, auth, resource_ids_from_bookings, max_workers)
            f_rooms_cache = ex.submit(build_rooms_cache, auth, room_ids_from_bookings, max_workers)

            req_cache = f_req_cache.result()
            answers_cache = f_ans_cache.result()
            resource_q_cache = f_res_cache.result()
            rooms_cache = f_rooms_cache.result()

        # Get the tags to create the tag groups (event instance tag map, )
        tag_groups_payload = fetch_tag_groups_with_tags(auth)

        # Create resource id extra variable
        resource_ids_extra: List[str] = []

        # Step through the resource requests cache, and get the key data from the API response and append the ID to the resource ID extra
        for _, blob in req_cache.items():
            req_data = blob.get("request") or {}
            req_rel = req_data.get("relationships", {}) or {}
            rref = safe_get(req_rel, "resource", "data", default=None)
            if isinstance(rref, dict) and rref.get("id"):
                resource_ids_extra.append(rref["id"])

        # Sort and deduplicate resource ID extra list, then see what ids are missing
        resource_ids_extra = sorted(set([r for r in resource_ids_extra if r]))
        missing = [rid for rid in resource_ids_extra if rid not in resource_q_cache]

        # If any IDs are missing then go through and try to find the necessary data for that ID0
        if missing:
            res_cache_2 = build_resource_questions_cache(auth, missing, max_workers)
            resource_q_cache.update(res_cache_2)

        # Given group ID, which is the staff group, get the owners from PCO. Owners are people who create events in calendar. Set in environment variables
        group_id = os.getenv("PCO_GROUP_ID")
        owners_rows = fetch_group_members_owner_table(auth, group_id)


        # From all the data gathered, put it all together into tables that are essentially the same as Matt's tables
        tables = build_relational_tables(
            payload, tz,
            req_cache,
            resource_q_cache,
            answers_cache,
            rooms_cache,
            tag_groups_payload,
            owners_rows
        )
    
    # Calculate the amount of GB-seconds it would take to run this file, to calculate potential cost in Azure Functions
    r = m.result()
    logging.info(
         f"COST[{r.name}] executions={r.billed_executions} duration_s={r.duration_s:.6f} "
        f"peak_rss_mb={r.peak_rss_mb:.1f} gb_seconds={r.sampled_gb_seconds:.6f}")

    # Return tables to whatever function called this one
    return tables


# Main, really only used if you want to verify output (will need to add those statements), and time how long it takes
def main():
    tables = extract_tables()


# Timed to see how long it takes to get data as well
if __name__ == "__main__":
    start = time.perf_counter()
    main()
    elapsed = time.perf_counter() - start
    print(f"\nTotal runtime: {elapsed:.3f} seconds")
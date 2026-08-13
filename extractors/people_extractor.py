#!/usr/bin/env python3
import os
import time
import requests
from typing import Dict, Any, List, Optional, Tuple, Iterator
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

from extractors.api_fetcher import pco_get, _get_thread_session
from utils.response_parsers import safe_get, index_included, process_person_from_payload
from utils.env_fetcher import get_auth_from_env, PCO_PEOPLE_INCLUDE_PERSON, PCO_PEOPLE_INCLUDE_FIELD_DATA
from utils.datatable_helpers import build_tables


# Full people extractor that fetches all data from People endpoint, parses, and organizes into tables for upserting


# Threaded function to go through all the pages of the API call, whether that is field_data or people; could be created into a separate file as a function called but not yet lol
def pco_iter_pages_threaded(
    path: str,
    auth: Tuple[str, str],
    params: Optional[Dict[str, str]] = None,
    per_page: int = 100,
    workers: int = 8,
    max_in_flight: Optional[int] = None,
) -> Iterator[Dict[str, Any]]:
    # Make params empty if set to none to successfully make API request
    if params is None:
        params = {}

    # Make per_page either user-defined or 100 (API max allowed)
    per_page = max(1, min(int(per_page), 100))
    # Set amount of workers to fetch (typically 8)
    workers = max(1, int(workers))
    
    # Set max workers allowed in use
    if max_in_flight is None:
        max_in_flight = workers * 3
    else:
        max_in_flight = max(1, int(max_in_flight))

    # Function that gets offset needed in API call, makes API call, and then returns offset, API response, and how long the data section of the API is
    def fetch_offset(off: int) -> Tuple[int, Dict[str, Any], int]:
        # Give each thread its own session
        sess = _get_thread_session()
        # Set parameters for API call
        page_params = dict(params)
        # Per page parameter
        page_params["per_page"] = str(per_page)
        # OFfset parameter
        page_params["offset"] = str(off)
        # Send request to the API and then get the JSON response
        payload = pco_get(session=sess, path=path, auth=auth, params=page_params)
        # Number of items in data section of the JSON, which is used later to determine if it is the last page
        n = len(payload.get("data", []) or [])
        # Return data
        return off, payload, n

    next_submit = 0          # next offset to schedule
    next_yield = 0           # next offset we want to yield (keeps order)
    end_offset: Optional[int] = None  # set when we find first short page

    in_flight: Dict[int, Any] = {}        # offset -> Future
    completed: Dict[int, Dict[str, Any]] = {}  # offset -> payload

    # Set muti-thread process to fetch multiple pages at a time
    with ThreadPoolExecutor(max_workers=workers) as ex:
        while True:
            # Send workers to get data if not at end and not over max workers allowed in use
            while len(in_flight) < max_in_flight and (end_offset is None or next_submit <= end_offset):
                # Send worker off and get data in return
                fut = ex.submit(fetch_offset, next_submit)
                # Add data and offset to in flight dict to track it
                in_flight[next_submit] = fut
                # Increase offset for the next worker being sent
                next_submit += per_page

            # If nothing in flight and nothing left to yield, we're done
            if not in_flight and (end_offset is not None and next_yield > end_offset):
                break

            # Wait for at least one to complete if we still have work
            if in_flight:
                # Wait for API call to finish
                done, _ = wait(in_flight.values(), return_when=FIRST_COMPLETED)
                # Process through finished API calls
                for fut in done:
                    # Parse offset, JSON, number of items as returned from fetch_offset function
                    off, payload, n = fut.result()
                    # Signal offset as done, moving data to completed dict
                    completed[off] = payload
                    # Remove JSON from in flight dict
                    in_flight.pop(off, None)

                    # First short page defines the last meaningful offset
                    if n < per_page and end_offset is None:
                        end_offset = off

            # Send data back in some order
            while next_yield in completed:
                if end_offset is not None and next_yield > end_offset:
                    break
                # Send data back to the func that called this one
                yield completed.pop(next_yield)
                # Increase offset for the next yield call, making it somewhat in order
                next_yield += per_page

            # Exit when we've yielded through the end and nothing else is pending
            if end_offset is not None and next_yield > end_offset and not in_flight:
                break

# Build the custom fields for each person
def build_fields_by_person(
    session: requests.Session,
    auth: Tuple[str, str],
    workers: int = 8,
    per_page: int = 100
) -> Dict[str, List[Dict[str, Any]]]:

    fields_by_person: Dict[str, List[Dict[str, Any]]] = {}

    params = {"include": PCO_PEOPLE_INCLUDE_FIELD_DATA}

    for payload in pco_iter_pages_threaded(
        "/people/v2/field_data",
        auth,
        params=params,
        per_page=per_page,
        workers=workers
    ):
        data = payload.get("data", []) or []
        inc = index_included(payload.get("included", []) or [])

        for datum in data:
            cust = safe_get(datum, "relationships", "customizable", "data", default=None)

            if not isinstance(cust, dict):
                continue

            if cust.get("type") != "Person":
                continue

            person_id = cust.get("id")

            if not person_id:
                continue

            value = safe_get(datum, "attributes", "value")

            # -----------------------------
            # Field Definition
            # -----------------------------
            fd_ref = safe_get(datum, "relationships", "field_definition", "data", default={}) or {}
            fd_type = fd_ref.get("type")
            fd_id = fd_ref.get("id")

            field_definition = inc.get((fd_type, fd_id), {}) if fd_type and fd_id else {}
            fd_attr = field_definition.get("attributes", {}) or {}

            field_definition_name = fd_attr.get("name")
            field_definition_slug = fd_attr.get("slug")
            field_definition_data_type = fd_attr.get("data_type")

            # -----------------------------
            # Tab
            # First try FieldDatum.relationships.tab
            # Then fall back to FieldDefinition.relationships.tab
            # -----------------------------
            tab_ref = safe_get(datum, "relationships", "tab", "data", default=None)

            if not isinstance(tab_ref, dict):
                tab_ref = safe_get(field_definition, "relationships", "tab", "data", default=None)

            tab_type = tab_ref.get("type") if isinstance(tab_ref, dict) else None
            tab_id = tab_ref.get("id") if isinstance(tab_ref, dict) else None

            tab_obj = inc.get((tab_type, tab_id), {}) if tab_type and tab_id else {}
            tab_attr = tab_obj.get("attributes", {}) or {}

            tab_name = tab_attr.get("name")

            # -----------------------------
            # Field Option
            # For dropdown/list fields, this gives the readable selected value
            # -----------------------------
            opt_ref = safe_get(datum, "relationships", "field_option", "data", default=None)
            option_value = None
            option_id = None

            if isinstance(opt_ref, dict) and opt_ref.get("type") and opt_ref.get("id"):
                option_id = opt_ref.get("id")
                opt_obj = inc.get((opt_ref.get("type"), opt_ref.get("id")), {})
                option_value = safe_get(opt_obj, "attributes", "value")

            row = {
                "field_definition_id": fd_id,
                "field_definition_name": field_definition_name,
                "field_definition_slug": field_definition_slug,
                "field_definition_data_type": field_definition_data_type,

                "tab_id": tab_id,
                "tab_name": tab_name,

                "value": value,
                "option_id": option_id,
                "option_value": option_value,

                # Use this for display because dropdown fields are more readable this way
                "display_value": option_value if option_value not in (None, "") else value,
            }

            fields_by_person.setdefault(person_id, []).append(row)

    for pid, rows in fields_by_person.items():
        rows.sort(
            key=lambda r: (
                r.get("tab_name") or "",
                r.get("field_definition_name") or ""
            )
        )

    return fields_by_person


def extraction() -> Dict[str, Dict[str, Dict[str, Dict[str, Any]]]]:
    tables: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]] = {}
    processing: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]] = {}
    # Record time to see how long it takes to get all the data
    t0 = time.perf_counter()
    # Keep track of how many people we've processed, to report at the end
    count = 0

    per_page = int(os.getenv("PCO_PEOPLE_PAGE_LIMIT", "100"))
    workers = int(os.getenv("PCO_MAX_WORKERS", "8"))

    # Get authentication from the environment variables
    auth = get_auth_from_env()

    try:
        # Start http session to make API calls
        with requests.Session() as session:
            # Build one global custom-fields index first (batched)
            fields_by_person = build_fields_by_person(session, auth, per_page=100, workers=workers)

            # Bulk: page through people with includes (no per-person GET)
            params = {"include": PCO_PEOPLE_INCLUDE_PERSON}  # Set params as emails,phone_numbers,addresses,households.people
            # See how many people we have data for, used when there is a limit of people to process through
            yielded = 0

            # Iterate through each page of people received, since pco_iter yields data bit by bit and process it
            for payload in pco_iter_pages_threaded("/people/v2/people", auth, params=params, per_page=per_page, workers=workers):
                # Get data chunk from the JSON response, which is a list of people 
                people = payload.get("data", []) or []
                # Index the includes section for later
                inc_index = index_included(payload.get("included", []) or [])

                # Step through each person in the data chunk
                for person_obj in people:
                    # Get person ID
                    pid = person_obj.get("id")
                    # If no ID, then move on, since hard to keep track of them
                    if not pid:
                        continue
                    
                    processing = process_person_from_payload(
                        person_obj,
                        inc_index,
                        fields_by_person.get(pid, [])
                    )
                    # Process each person
                    tables.update(processing)
                    
                    # Increment counters
                    count += 1
                    yielded += 1
                    #if yielded >= 5:
                    #    built = build_tables(tables)
                    #    return built   
                
    finally:
        elapsed = time.perf_counter() - t0
        #print(f"TOTAL: {count} people in {elapsed:.2f}s")

    built = build_tables(tables)
    return built

def main() -> None:
    tables = extraction()

    print("\nExtraction complete. Table counts:")
    print(len(tables))
    for name, rows in tables.items():
        print(f"  {name}: {len(rows)} rows")
    # If you want to see a sample, uncomment:
    """for name, rows in tables.items():
         if rows:
             print(f"\n{name} first row:")
             print(rows[0])"""



if __name__ == "__main__":
    main()

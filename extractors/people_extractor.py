#!/usr/bin/env python3
import os
import sys
import pprint
import time
import argparse
import requests
from typing import Dict, Any, List, Optional, Tuple, Iterator
import threading
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import shutil

from extractors.api_fetcher import pco_get
from utils.response_parsers import safe_get, index_included, get_included_value, return_sorted
from dataverse.credentials_urls import get_auth_from_env

# How many people to fetch, but still needs to fetch all the people data so doesn't speed it up too much
DEFAULT_PEOPLE_LIMIT = os.getenv("PCO_PEOPLE_LIMIT", "all")

# How many to fetch per API pull (usually 100, the max)
PER_PAGE_DEFAULT = 100


# Person include parameter used in later sections of the code
INCLUDE_PERSON = "inactive_reason,marital_status,emails,phone_numbers,addresses,households.people"
# Field data include parameter used in later sections of the code
INCLUDE_FIELD_DATA = "field_definition,field_option,tab"

# Function that prints the header nice and neat
def print_header(title: str):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


# Function to print items (typically attributes) idented, and sorted by the key name
def print_kv_sorted(obj: Dict[str, Any], indent: int = 2):
    pad = " " * indent
    # Sort by the key
    for k in sorted(obj.keys()):
        # Get value by key
        v = obj.get(k)
        # Print out the key with the value, with an indent
        print(f"{pad}{k}: {v}")

# Give each thread its own storage, ensuring that data remains seperate
_thread_local = threading.local()


# Give each thread worker its own independent request session
def _get_thread_session() -> requests.Session:
    # Get session for the current thread passed in
    s = getattr(_thread_local, "session", None)
    # If no session exists, create one for the thread, putting it in the thread local storage
    if s is None:
        s = requests.Session()
        _thread_local.session = s
    
    # Return thread session
    return s

# Threaded function to go through all the pages of the API call, whether that is field_data or people; could be created into a seperate file as a function called but not yet lol
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

    params = {"include": INCLUDE_FIELD_DATA}

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


# Function to process through person's data and then print out processed data
def process_person_from_payload(person_obj: Dict[str, Any], inc_index: Dict[Tuple[str, str], Dict[str, Any]], fields_clean: List[Dict[str, Any]], name_only: bool = False) -> Dict[str, Dict[str, Dict[str, Dict[str, Any]]]]:
    person_data: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]] = {}


    # Get persons ID from JSON
    person_id = person_obj.get("id")
    # Get person's attributes from the data
    p_attr = person_obj.get("attributes", {}) or {}
    rels = person_obj.get("relationships", {}) or {}

    if name_only:
        name = p_attr.get("name") or f"{p_attr.get('first_name','')}".strip() or "(no name)"
        print(f"{name} ({person_id})")
        return

    # Resolve included relationship values
    marital_status = get_included_value(rels, inc_index, "marital_status")
    inactive_reason = get_included_value(rels, inc_index, "inactive_reason")

    # Build a core attributes object with the extra resolved values
    core_attrs = dict(p_attr)
    core_attrs["marital_status"] = marital_status
    core_attrs["inactive_reason"] = inactive_reason

    person_data[person_id] = {}
    person_data[person_id]["core_attributes"] = {}
    person_data[person_id]["core_attributes"]["1"] = {}
    person_data[person_id]["core_attributes"] = return_sorted(core_attrs)

    # Get the emails for the person
    emails_refs = safe_get(rels, "emails", "data", default=[]) or []
    # Get phone numbers for the person
    phones_refs = safe_get(rels, "phone_numbers", "data", default=[]) or []
    # Get address for person
    addrs_refs = safe_get(rels, "addresses", "data", default=[]) or []
    # Get household data for person
    households_refs = safe_get(rels, "households", "data", default=[]) or []
    person_data[person_id]["emails"] = {}
    person_data[person_id]["phones"] = {}
    person_data[person_id]["addresses"] = {}
    # Step through the resources
    counter = 0
    for idx, ref in enumerate(emails_refs, start=1):
        counter += 1
        # Get type and ID of resource
        t, i = ref.get("type"), ref.get("id")
        # Get object itself, which contains the values needed
        obj = inc_index.get((t, i), {})
        # Get values itself
        attrs = obj.get("attributes", {}) or {}
        person_data[person_id]["emails"][counter] = {}
        
        for k in sorted(attrs.keys()):
            # Get value by key
            v = attrs.get(k)
            person_data[person_id]["emails"][counter][k] = {v}

    counter = 0
    for idx, ref in enumerate(phones_refs, start=1):
        counter += 1
        # Get type and ID of resource
        t, i = ref.get("type"), ref.get("id")
        # Get object itself, which contains the values needed
        obj = inc_index.get((t, i), {})
        # Get values itself
        attrs = obj.get("attributes", {}) or {}
        person_data[person_id]["phones"][counter] = {}
        for k in sorted(attrs.keys()):
            # Get value by key
            v = attrs.get(k)
            person_data[person_id]["phones"][counter][k] = {v}

    # Step through the resources
    counter = 0
    for idx, ref in enumerate(addrs_refs, start=1):
        counter += 1
        # Get type and ID of resource
        t, i = ref.get("type"), ref.get("id")
        # Get object itself, which contains the values needed
        obj = inc_index.get((t, i), {})
        # Get values itself
        attrs = obj.get("attributes", {}) or {}
        person_data[person_id]["addresses"][counter] = {}
        for k in sorted(attrs.keys()):
            # Get value by key
            v = attrs.get(k)
            person_data[person_id]["addresses"][counter][k] = {v}

    person_data[person_id]["household"] = {}
    person_data[person_id]["household"]["1"] = {
        "household_ids": set()
    }


    # If no household data, print none
    if not households_refs:
        person_data[person_id]["household"]["1"]["household_id"] = "N/A"
    
    # If there is household data then step through and print as necessary
    else:
        for idx, href in enumerate(households_refs, start=1):
            # Household type and household ID
            ht, hid = href.get("type"), href.get("id")
            # Get household from the include index using the type and ID found
            hh = inc_index.get((ht, hid), {})
            # Get household attributes
            hh_attr = hh.get("attributes", {}) or {}

            person_data[person_id]["household"]["1"]["household_id"] = str(hid)

            for k in sorted(hh_attr.keys()):
                # Get value by key
                v = hh_attr.get(k)
                person_data[person_id]["household"]["1"][k] = v


            # Get household people data (member 1 data, etc)
            hh_people_refs = safe_get(hh, "relationships", "people", "data", default=[]) or []
            
            # If household people data exists then print
            if hh_people_refs:

                # Step through each person in the household
                for pref in hh_people_refs:
                    # Get type and ID of person
                    
                    pt, pid = pref.get("type"), pref.get("id")
                    person_data[person_id]["household"]["1"]["household_ids"].add(pid)


    person_data[person_id]["custom_fields"] = {}
    person_data[person_id]["custom_tabs"] = {}
    
    counter = 0
    if not fields_clean:
        person_data[person_id]["custom_fields"]["1"] = {}
        person_data[person_id]["custom_fields"]["1"]["field_name"] = "N/A"
    else:
        # Step through each custom field
        for f in fields_clean:
            counter += 1
            person_data[person_id]["custom_fields"][counter] = {}
            person_data[person_id]["custom_tabs"][counter] = {}
            # Get name, data type, slug (name with no spaces), value, and option if it is a dropdown
            name = f.get("field_definition_name") or "(Unnamed Field)"
            dtype = f.get("field_definition_data_type")
            value = f.get("value")
            tab_name = f.get("tab_name") or "(No Tab)"
            tab_id = f.get("tab_id") or "(no tab id)"
            field_id = f.get("field_definition_id") or "(no field definition id)"

            person_data[person_id]["custom_tabs"][counter]["tab_name"] = tab_name
            person_data[person_id]["custom_tabs"][counter]["tab_id"] = tab_id

            person_data[person_id]["custom_fields"][counter]["field_name"] = name
            person_data[person_id]["custom_fields"][counter]["field_data_type"] = dtype
            person_data[person_id]["custom_fields"][counter]["field_value"] = value
            person_data[person_id]["custom_fields"][counter]["field_tab_id"] = tab_id
            person_data[person_id]["custom_fields"][counter]["field_tab_name"] = tab_name
            person_data[person_id]["custom_fields"][counter]["field_id"] = field_id
    
    return person_data


def fetch_person_with_includes(session: requests.Session, person_id: str, auth: Tuple[str, str]) -> Dict[str, Any]:
    # Get parameters for the API request, marital reason, emails, phone numbers, etc
    params = {"include": INCLUDE_PERSON}
    # Fetch data for the person and then return the JSON
    return pco_get(session=session, path=f"/people/v2/people/{person_id}", auth=auth, params=params)

# Function that gets the limit of people to fetch, process and then print
def _parse_limit(value: str) -> Optional[int]:
    # If no value given, no limit
    if value is None:
        return None
    # Make lowercase to parse easier
    v = value.strip().lower()
    # Same value as no limit
    if v in ("all", "everyone", "*"):
        return None
    # Cast as an int
    n = int(v)  
    # Return value or throw error if less than 1
    if n < 1:
        raise ValueError("limit must be >= 1 or 'all'")
    return n

def extraction() -> Dict[str, Dict[str, Dict[str, Dict[str, Any]]]]:
    tables: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]] = {}
    processing: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]] = {}
    # Record time to see how long it takes to get all the data
    t0 = time.perf_counter()
    # Keep track of how many people we've processed, to report at the end
    count = 0

    # Parse command-line arguments for person ID, limit, pagination, and workers
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--person-id", help="Process a single person ID (old behavior).")
    parser.add_argument("--limit", default=DEFAULT_PEOPLE_LIMIT)
    parser.add_argument("--per-page", type=int, default=PER_PAGE_DEFAULT)
    parser.add_argument("--name-only", action="store_true")
    parser.add_argument("--workers", type=int, default=int(os.getenv("PCO_MAX_WORKERS", "8")))
    args = parser.parse_args()

    # Get authentication from the environment variables
    auth = get_auth_from_env()
    # Get limit of how many people to process through
    limit = _parse_limit(str(args.limit))


    try:
        # Start http session to make API calls
        with requests.Session() as session:
            # Build one global custom-fields index first (batched)
            fields_by_person = build_fields_by_person(session, auth, per_page=100, workers=args.workers)

            if args.person_id:
                # For single person mode, fetch data, not really that fast cause of the field data but oh well
                payload = fetch_person_with_includes(session, args.person_id, auth)
                # Get includes for person
                inc_index = index_included(payload.get("included", []) or [])
                # Get persons data from JSON
                person_obj = payload.get("data", {}) or {}
                # Get processed custom field data for person
                fields_clean = fields_by_person.get(args.person_id, [])
                # Process data for person
                process_person_from_payload(person_obj, inc_index, fields_clean, name_only=args.name_only)
                return

            # Bulk: page through people with includes (no per-person GET)
            params = {"include": INCLUDE_PERSON}  # Set params as emails,phone_numbers,addresses,households.people
            # See how many people we have data for, used when there is a limit of people to process through
            yielded = 0

            # Iterate through each page of people received, since pco_iter yields data bit by bit and process it
            for payload in pco_iter_pages_threaded("/people/v2/people", auth, params=params, per_page=args.per_page, workers=args.workers):
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
                        fields_by_person.get(pid, []),
                        name_only=args.name_only
                    )
                    # Process each person
                    tables.update(processing)
                    
                    # Increment counters
                    count += 1
                    yielded += 1

                    # If there is a limit on how many people to process, end loop after limit reached
                    if limit is not None and yielded >= limit:
                        # Calculate time taken to fetch and process data, as well as amount of people fetched
                        elapsed = time.perf_counter() - t0
                        print(f"TOTAL 2: {count} people in {elapsed:.2f}s")
                        return
    finally:
        elapsed = time.perf_counter() - t0
        print(f"TOTAL: {count} people in {elapsed:.2f}s")

    return tables

def main() -> None:
    tables = extraction()



if __name__ == "__main__":
    main()

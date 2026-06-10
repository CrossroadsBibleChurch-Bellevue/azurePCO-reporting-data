#!/usr/bin/env python3
import os
import sys
import time
import argparse
import requests
from typing import Dict, Any, List, Optional, Tuple, Iterator
import threading
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import shutil

from extractors.api_fetcher import pco_get
# Base PCO url
BASE_URL = "https://api.planningcenteronline.com"

# How many people to fetch, but still needs to fetch all the people data so doesn't speed it up too much
DEFAULT_PEOPLE_LIMIT = os.getenv("PCO_PEOPLE_LIMIT", "all")

# How many to fetch per API pull (usually 100, the max)
PER_PAGE_DEFAULT = 100

# Global counter variable, temp
COUNTING = 0

# Person include parameter used in later sections of the code
INCLUDE_PERSON = "inactive_reason,marital_status,emails,phone_numbers,addresses,households.people"
# Field data include parameter used in later sections of the code
INCLUDE_FIELD_DATA = "field_definition,field_option,tab"


# Keeps track of how many API calls have been made, for the progress bar
_API_CALLS = 0
# Lock helps make sure count is calculate properly
_API_CALLS_LOCK = threading.Lock()

# Function that increase API call count
def _api_calls_inc(n: int = 1) -> None:
    global _API_CALLS
    # Use the API call lock to keep accurate count
    with _API_CALLS_LOCK:
        _API_CALLS += n

# Function that returns API call count
def _api_calls_get() -> int:
    # Use lock
    with _API_CALLS_LOCK:
        return _API_CALLS


# Function that prints progress of how many API calls have been made, how many per second approximately, how long the program has run for
def _progress_reporter(stop_event: threading.Event, start_t: float, label: str = "API calls") -> None:
    # Check API progress
    last = -1

    # Until signal to stop, continue to print progress updates about API calls, every 0.2 seconds
    while not stop_event.is_set():
        # Get API call count
        calls = _api_calls_get()

        # If count is different, print update
        if calls != last:
            # Calculate elapsed time
            elapsed = max(0.0001, time.perf_counter() - start_t)
            # Calculate call rate
            rate = calls / elapsed
            # Get columns for terminal
            cols = shutil.get_terminal_size((80, 20)).columns
            # Set bar width
            bar_w = max(10, min(40, cols - 40))
            # Calculate next position for progress bar
            pos = calls % bar_w
            # Print progress bar
            bar = ["-"] * bar_w
            bar[pos] = "#"
            bar = "".join(bar)
            # Formulate output message
            msg = f"\r{label}: {calls:,} | {rate:,.1f}/s | {elapsed:,.1f}s [{bar}]"
            # Print progress
            print(msg.ljust(cols - 1), end="", flush=True)
            last = calls
        time.sleep(0.2)

    # Get last API call count
    calls = _api_calls_get()
    # Calculate time
    elapsed = time.perf_counter() - start_t
    # Calculate rate
    rate = calls / max(elapsed, 0.0001)
    # Get column
    cols = shutil.get_terminal_size((80, 20)).columns
    # Print final progress
    print(f"\rAPI calls: {calls:,} | {rate:,.1f}/s | {elapsed:,.1f}s".ljust(cols - 1), end="\n", flush=True)


# Get authentication from environmental variables
def get_auth_from_env() -> Tuple[str, str]:
    # App ID from PCO, also known as Client ID
    app_id = os.getenv("PCO_APP_ID")
    # Secret ID from PCO
    secret = os.getenv("PCO_SECRET")
    # If app or secret is not set, report error
    if not app_id or not secret:
        raise RuntimeError(
            "Missing env vars. Set:\n"
            "  PCO_APP_ID=your_app_id\n"
            "  PCO_SECRET=your_secret\n"
        )
    
    # Return app and secret
    return app_id, secret


# Function to index the includes to make it easier to get certain data later, make it a lil more neat
def index_included(included: List[Dict[str, Any]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    # Outgoing dictionary for includes
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    
    # Step through each item of the includes
    for item in included or []:
        # Get type of item
        t = item.get("type")

        # Get ID of item
        i = item.get("id")

        # If both type and ID exist, then set them as key in includes, and set item as value, to search for later
        if t and i:
            out[(t, i)] = item
    
    # Return dict of includes
    return out

# Function is essentially trying to step through the nest JSON dictionary that is returned from the API
def safe_get(dct: Dict[str, Any], *keys, default=None):
    # Given dictionary and keys (relationships, field data, etc)
    cur = dct
    # Iterate through each key
    for k in keys:
        # Check if key is in the current dictionary passed into the function, if it is, set current dictionary to the data of the key, if it is not, return default (usually none)
        if not isinstance(cur, dict) or k not in cur:
            return default
        # Set current dictionary to value of the key
        cur = cur[k]

    # Return final value found, so last key searched for
    return cur


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
    # Create dictionary to hold custom fields by each persons ID (str)
    fields_by_person: Dict[str, List[Dict[str, Any]]] = {}

    # Parameters to pass through to the API, all the includes in the query
    params = {"include": INCLUDE_FIELD_DATA}  # field_definition,field_option,tab
    for payload in pco_iter_pages_threaded("/people/v2/field_data", auth, params=params, per_page=per_page, workers=workers): # Iterate through each page of the custom field data API, using 8 workers to speed up process
        # Get all data from the data section of the JSON response
        data = payload.get("data", []) or []
        # Get the included section of data from the JSON response and get it indexed
        inc = index_included(payload.get("included", []) or [])

        # Loop to go through the data section of the JSON
        for datum in data:
            # FieldDatum relates to Person via customizable relationship
            # Take data and step through the nested JSON data to get the person ID
            cust = safe_get(datum, "relationships", "customizable", "data", default=None)
            # If cust is not a dictionary, go to next loop iteration 
            if not isinstance(cust, dict):
                continue
            # If the type of relationship is not a person then go to the next loop iteration, ensures we only get field data related to people
            if cust.get("type") != "Person":
                continue
            # Get person ID for the field data to associated it with right person
            person_id = cust.get("id")
            # If no person ID, go to next loop
            if not person_id:
                continue
            
            # Step through nested JSON to get the value of the custom field, not other wonky data
            value = safe_get(datum, "attributes", "value")
            
            # Get field definition as a dictionary, which includes type and ID
            fd_ref = safe_get(datum, "relationships", "field_definition", "data", default={}) or {}
            # Get field defintion type and ID
            def_type, def_id = fd_ref.get("type"), fd_ref.get("id")
            # Get the appropriate dield definition included section, to later get name, tab ID, slug, data type, etc of custom field
            definition = inc.get((def_type, def_id), {}) if def_type and def_id else {}
            # Store the actual data we desire (data type, tab id, etc) in dictionary for access later
            def_attr = definition.get("attributes", {}) or {}

            # Get field option as dictionary, for use cases where value is an option, marital status, etc
            opt_ref = safe_get(datum, "relationships", "field_option", "data", default=None)
            # Inital set option value as none for later if it is true
            option_value = None
            # If option refernce is a valid dictionary and has type and ID, then go through and parse
            if isinstance(opt_ref, dict) and opt_ref.get("type") and opt_ref.get("id"):
                # Get type and ID from option reference
                opt_obj = inc.get((opt_ref.get("type"), opt_ref.get("id")), {})
                # Go through nested JSON to get actual value of the option (single for marital status)
                option_value = safe_get(opt_obj, "attributes", "value")

            # Create field row, consisting of the name of the field, corresponding slug, data type, tab ID, value, and if it is and option value, that
            row = {
                "name": def_attr.get("name"),
                "slug": def_attr.get("slug"),
                "data_type": def_attr.get("data_type"),
                "tab_id": def_attr.get("tab_id"),
                "value": value,
                "option_value": option_value,
            }

            # Append row to appropriate person
            fields_by_person.setdefault(person_id, []).append(row)

    # Sort person's fields by tab ID and name to keep consisent across all people
    for pid, rows in fields_by_person.items():
        rows.sort(key=lambda r: ((r.get("tab_id") or ""), (r.get("name") or "")))

    # Return dictionary of custom fields
    return fields_by_person


# Function to process through person's data and then print out processed data
def process_person_from_payload(person_obj: Dict[str, Any], inc_index: Dict[Tuple[str, str], Dict[str, Any]], fields_clean: List[Dict[str, Any]], name_only: bool = False) -> Dict[str, Dict[str, Dict[str, Any]]]:
    person_data: Dict[str, Dict[str, Dict[str, Any]]] = {}
    # global variable to temporarily only print 5 people to not get spammed with data lol
    global COUNTING
    COUNTING += 1

    # Get persons ID from JSON
    person_id = person_obj.get("id")
    # Get person's attributes from the data
    p_attr = person_obj.get("attributes", {}) or {}
    rels = person_obj.get("relationships", {}) or {}

    if name_only:
        name = p_attr.get("name") or f"{p_attr.get('first_name','')}".strip() or "(no name)"
        print(f"{name} ({person_id})")
        return

    # Fun blob of code where I was trying to figure out how to get included, will clean up later
    #print(person_obj)
    #print(inc_index)
    #print(fields_clean)
    #os._exit(0)
    """included = inc_index
    print(included)
    if included is not None:
        types = [d["type"] for d in included]
        print(types)
        filtered_types = [d for d in included if d['type'] == 'MaritalStatus']
        for filtering in filtered_types:
            value = filtering.get("attributes")
            true_value = value.get("value")
            print(true_value)

        filtered_types = [d for d in included if d['type'] == 'InactiveReason']
        for filtering in filtered_types:
            value = filtering.get("attributes")
            true_value = value.get("value")
            print(true_value)

        os._exit(0)"""

    # Print person and their core attributes, which are essentially name, gender, birth day, etc.
    print_header(f"PERSON (ID: {person_id}) — ALL ATTRIBUTES")
    person_data[person_id] = {}
    person_data[person_id]["core_attributes"] = {}
    for k in sorted(p_attr.keys()):
        # Get value by key
        v = p_attr.get(k)
        person_data[person_id]["core_attributes"][k] = {v}

    print(person_data)
    #print_kv_sorted(p_attr, indent=2)

    # Get the emails for the person
    emails_refs = safe_get(rels, "emails", "data", default=[]) or []
    # Get phone numbers for the person
    phones_refs = safe_get(rels, "phone_numbers", "data", default=[]) or []
    # Get address for person
    addrs_refs = safe_get(rels, "addresses", "data", default=[]) or []
    # Get household data for person
    households_refs = safe_get(rels, "households", "data", default=[]) or []

    # Print emails, phone number, addresses that were found
    print_resource_list("EMAILS — ALL ATTRIBUTES", emails_refs, inc_index)
    print_resource_list("PHONE NUMBERS — ALL ATTRIBUTES", phones_refs, inc_index)
    print_resource_list("ADDRESSES — ALL ATTRIBUTES", addrs_refs, inc_index)

    # Print household data
    print_header("HOUSEHOLDS — ALL ATTRIBUTES (+ PEOPLE IF INCLUDED)")

    # If no household data, print none
    if not households_refs:
        print("(none)")
    
    # If there is household data then step through and print as necessary
    else:
        for idx, href in enumerate(households_refs, start=1):
            # Household type and household ID
            ht, hid = href.get("type"), href.get("id")
            # Get household from the include index using the type and ID found
            hh = inc_index.get((ht, hid), {})
            # Get household attributes
            hh_attr = hh.get("attributes", {}) or {}
            # Print household ID
            print(f"\n#{idx} Household ({hid})")
            # Print household data (primary contact, member count, etc)
            print_kv_sorted(hh_attr, indent=2)

            # Get household people data (member 1 data, etc)
            hh_people_refs = safe_get(hh, "relationships", "people", "data", default=[]) or []
            
            # If household people data exists then print
            if hh_people_refs:
                print("  People:")

                # Step through each person in the household
                for pref in hh_people_refs:
                    # Get type and ID of person
                    pt, pid = pref.get("type"), pref.get("id")
                    # Get includes data about the person
                    pobj = inc_index.get((pt, pid), {})
                    # Get data about person
                    pattr = pobj.get("attributes", {}) or {}
                    # Print person and sorted data about them
                    print(f"    - Person ({pid})")
                    for k in sorted(pattr.keys()):
                        print(f"        {k}: {pattr.get(k)}")
            else:
                print("  People: (not included / none)")

    # Print custom fields data
    print_header(f"CUSTOM FIELDS — RESOLVED (TOTAL: {len(fields_clean)})")
    if not fields_clean:
        print("(none)")
    else:
        # Step through each custom field
        for f in fields_clean:
            # Get name, data type, slug (name with no spaces), value, and option if it is a dropdown
            name = f.get("name") or "(Unnamed Field)"
            dtype = f.get("data_type")
            slug = f.get("slug")
            value = f.get("value")
            opt = f.get("option_value")
            # Print custom field data that was retrieved
            if opt is not None and opt != "":
                print(f"- {name} ({dtype}, slug={slug}): {value}  [option={opt}]")
            else:
                print(f"- {name} ({dtype}, slug={slug}): {value}")
    
    if COUNTING >= 5:
        os._exit(0)
    
    return 
    

# Function that prints out a resource list (emails, phone number, etc)
def print_resource_list(
    title: str,
    refs: List[Dict[str, Any]],
    inc_index: Dict[Tuple[str, str], Dict[str, Any]],
):
    # Print header and if no resources to print, then print none
    print_header(title)
    if not refs:
        print("(none)")
        return

    # Step through the resources
    for idx, ref in enumerate(refs, start=1):
        # Get type and ID of resource
        t, i = ref.get("type"), ref.get("id")
        # Get object itself, which contains the values needed
        obj = inc_index.get((t, i), {})
        # Get values itself
        attrs = obj.get("attributes", {}) or {}
        # Print number in its section (email #1, email #2), tag and ID
        print(f"\n#{idx}  {t} ({i})")
        # Print actual data associated with resource, email address, primary, location, etc.
        print_kv_sorted(attrs, indent=2)


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

def extraction() -> Dict[str, Dict[str, Dict[str, Any]]]:
    tables = Dict[str, Dict[str, Dict[str, Any]]]
    # Record time to see how long it takes to get all the data
    t0 = time.perf_counter()
    # Create and start the stop progress reporter thread
    _stop_progress = threading.Event()
    # This thread will print progress updates about API calls every 0.2 seconds until we signal it to stop
    _progress_thread = threading.Thread(target=_progress_reporter, args=(_stop_progress, t0), daemon=True)
    # Start the progress reporter thread before we begin making API calls, so it can track them from the start
    _progress_thread.start()
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

                #fields_by_person = build_fields_by_person(session, auth, per_page=100, workers=args.workers)

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
                        print(f"TOTAL: {count} people in {elapsed:.2f}s")
                        return
    finally:
        # Stop threads, print final time taken and people processed
        _stop_progress.set()
        _progress_thread.join(timeout=2.0)

        elapsed = time.perf_counter() - t0
        print(f"TOTAL: {count} people in {elapsed:.2f}s")
        return tables

def main() -> None:
    tables = extraction()



if __name__ == "__main__":
    main()

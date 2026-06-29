#!/usr/bin/env python3
import os
import time
import requests
from typing import Dict, Any, List, Optional, Tuple, Iterator, Callable
import threading
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

from extractors.api_fetcher import pco_get
from utils.response_parsers import safe_get, index_included, get_included_value, return_sorted
from utils.env_fetcher import get_auth_from_env, PCO_PEOPLE_INCLUDE_PERSON, PCO_PEOPLE_INCLUDE_FIELD_DATA
from extractors.schemas.people_schemas import build_row_people
from utils.datatable_helpers import upsert_row


# Give each thread its own storage, ensuring that data remains seperate
_thread_local = threading.local()

updated_at_filter = os.getenv("PCO_UPDATED_SINCE")


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


def stop_when_older_than_cutoff(payload: Dict[str, Any]) -> bool:
    for item in payload.get("data", []) or []:
        updated_at = safe_get(item, "attributes", "updated_at", default=None)

        if updated_at and updated_at < updated_at_filter:
            return True

    return False


# Threaded function to go through all the pages of the API call, whether that is field_data or people; could be created into a separate file as a function called but not yet lol
def pco_iter_pages_threaded(
    path: str,
    auth: Tuple[str, str],
    params: Optional[Dict[str, str]] = None,
    per_page: int = 100,
    workers: int = 8,
    max_in_flight: Optional[int] = None,
    stop_condition: Optional[Callable[[Dict[str, Any]], bool]] = None,
) -> Iterator[Dict[str, Any]]:
    # Make params empty if set to none to successfully make API request
    if params is None:
        params = {}

    # Order all paginated API calls by most recently updated first
    params = dict(params)
    params["order"] = "-updated_at"

    updated_at_lock = threading.Lock()

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

        """for item in payload.get("data", []) or []:
            item_id = item.get("id")
            updated_at = safe_get(item, "attributes", "updated_at", default=None)

            if updated_at >= updated_at_filter:
                print("Updated at:", updated_at, "   before: ", updated_at_filter)"""

        # Number of items in data section of the JSON, which is used later to determine if it is the last page
        n = len(payload.get("data", []) or [])
        # Return data
        return off, payload, n

    next_submit = 0          # next offset to schedule
    next_yield = 0           # next offset we want to yield (keeps order)
    end_offset: Optional[int] = None  # set when we find first short page

    in_flight: Dict[int, Any] = {}        # offset -> Future
    completed: Dict[int, Dict[str, Any]] = {}  # offset -> payload

    stop_submitting = False
    last_submitted_offset: Optional[int] = None
    last_offset_to_yield: Optional[int] = None

    # Set muti-thread process to fetch multiple pages at a time
    with ThreadPoolExecutor(max_workers=workers) as ex:
        while True:
            # Send workers to get data if not at end and not over max workers allowed in use
            while (
                not stop_submitting
                and len(in_flight) < max_in_flight
                and (last_offset_to_yield is None or next_submit <= last_offset_to_yield)
            ):
                # Send worker off and get data in return
                fut = ex.submit(fetch_offset, next_submit)
                # Add data and offset to in flight dict to track it
                in_flight[next_submit] = fut
                last_submitted_offset = next_submit
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
                    if n < per_page:
                        stop_submitting = True
                        last_offset_to_yield = off if last_offset_to_yield is None else min(last_offset_to_yield, off)

                    # Custom stop condition:
                    # stop sending new API requests, but still drain already-submitted workers
                    if stop_condition is not None and stop_condition(payload):
                        stop_submitting = True

                        if last_submitted_offset is not None:
                            last_offset_to_yield = (
                                last_submitted_offset
                                if last_offset_to_yield is None
                                else min(last_offset_to_yield, last_submitted_offset)
                            )

            # Send data back in some order
            while next_yield in completed:
                if last_offset_to_yield is not None and next_yield > last_offset_to_yield:
                    break
                # Send data back to the func that called this one
                yield completed.pop(next_yield)
                # Increase offset for the next yield call, making it somewhat in order
                next_yield += per_page

            # Exit when we've yielded through the end and nothing else is pending
            if last_offset_to_yield is not None and next_yield > last_offset_to_yield and not in_flight:
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


# Function to process through person's data and then print out processed data
def process_person_from_payload(person_obj: Dict[str, Any], inc_index: Dict[Tuple[str, str], Dict[str, Any]], fields_clean: List[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, Dict[str, Any]]]]:
    person_data: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]] = {}


    # Get persons ID from JSON
    person_id = person_obj.get("id")
    # Get person's attributes from the data
    p_attr = person_obj.get("attributes", {}) or {}
    rels = person_obj.get("relationships", {}) or {}

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
    person_data[person_id]["core_attributes"]["1"] = return_sorted(core_attrs)

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
            person_data[person_id]["emails"][counter][k] = v

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
            person_data[person_id]["phones"][counter][k] = v

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
            person_data[person_id]["addresses"][counter][k] = v

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


def build_tables(parsed: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]]) -> Dict[str, Any]:


    addresses: Dict[str, Dict[str, Any]] = {}
    core_attributes: Dict[str, Dict[str, Any]] = {}
    custom_fields: Dict[str, Dict[str, Any]] = {}
    custom_tabs: Dict[str, Dict[str, Any]] = {}
    custom_values: Dict[str, Dict[str, Any]] = {}
    emails: Dict[str, Dict[str, Any]] = {}
    household: Dict[str, Dict[str, Any]] = {}
    phones: Dict[str, Dict[str, Any]] = {}

    for key1, dict_level2 in parsed.items():
        person_id = key1

        for key2, dict_level3 in dict_level2.items():
            table = key2

            for key3, dict_level4 in dict_level3.items():

                if table == "addresses":
                    upsert_row(addresses, build_row_people(
                        "address",
                        {"person_id": person_id,
                        "chunk": dict_level4,
                        }
                    ), pk="cr0b4_hash_id")
                elif table == "core_attributes":
                    upsert_row(core_attributes, build_row_people(
                        "core_attribute",
                        {"person_id": person_id,
                        "chunk": dict_level4,
                        }
                    ), pk="cr0b4_person_id")
                elif table == "custom_fields":
                    upsert_row(custom_fields, build_row_people(
                        "custom_fields",
                        {"person_id": person_id,
                        "chunk": dict_level4,
                        }
                    ), pk="cr0b4_hash_id")
                    upsert_row(custom_values, build_row_people(
                        "custom_values",
                        {"person_id": person_id,
                        "chunk": dict_level4,
                        }
                    ), pk="cr0b4_hash_id")
                elif table == "custom_tabs":
                    upsert_row(custom_tabs, build_row_people(
                        "custom_tabs",
                        {"person_id": person_id,
                        "chunk": dict_level4,
                        }
                    ), pk="cr0b4_hash_id")
                elif table == "emails":
                    upsert_row(emails, build_row_people(
                        "emails",
                        {"person_id": person_id,
                        "chunk": dict_level4,
                        }
                    ), pk="cr0b4_hash_id")
                elif table == "household":
                    upsert_row(household, build_row_people(
                        "household",
                        {"person_id": person_id,
                        "chunk": dict_level4,
                        }
                    ), pk="cr0b4_hash_id")
                elif table == "phones":
                    upsert_row(phones, build_row_people(
                        "phones",
                        {"person_id": person_id,
                        "chunk": dict_level4,
                        }
                    ), pk="cr0b4_hash_id")



    return {
        "address": list(addresses.values()),
        "core_attribute": list(core_attributes.values()),
        "custom_fields": list(custom_fields.values()),
        "custom_tabs": list(custom_tabs.values()),
        "custom_values": list(custom_values.values()),
        "emails": list(emails.values()),
        "household": list(household.values()),
        "phones": list(phones.values()),
    }

def extraction_updates() -> Dict[str, Dict[str, Dict[str, Dict[str, Any]]]]:
    tables: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]] = {}
    processing: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]] = {}
    updated_at_by_person: Dict[str, str] = {}
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
            for payload in pco_iter_pages_threaded("/people/v2/people", auth, params=params, per_page=per_page, workers=workers, stop_condition=stop_when_older_than_cutoff):
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
        print(f"TOTAL: {count} people in {elapsed:.2f}s")

    built = build_tables(tables)
    return built

def main() -> None:
    tables = extraction_updates()

    print("\nExtraction complete. Table counts:")
    print(len(tables))
    for name, rows in tables.items():
        print(f"  {name}: {len(rows)} rows")
    # If you want to see a sample, uncomment:
    for name, rows in tables.items():
         if rows:
             print(f"\n{name} first row:")
             print(rows[0])



if __name__ == "__main__":
    main()

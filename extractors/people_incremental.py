#!/usr/bin/env python3
import os
import time
import requests
from typing import Dict, Any, List, Optional, Tuple, Iterator
import threading
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
from requests import HTTPError

from extractors.api_fetcher import pco_get
from utils.response_parsers import safe_get, index_included, get_included_value, return_sorted
from utils.env_fetcher import get_auth_from_env, PCO_PEOPLE_INCLUDE_PERSON, PCO_PEOPLE_INCLUDE_FIELD_DATA
from extractors.schemas.people_schemas import build_row_people
from utils.datatable_helpers import upsert_row


# Give each thread its own storage, ensuring that data remains seperate
_thread_local = threading.local()

def parse_pco_datetime(value: str) -> datetime:
    if not value:
        raise ValueError("Missing datetime value")

    # PCO returns ISO strings like 2000-01-01T12:00:00Z
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    dt = datetime.fromisoformat(value)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def get_updated_at(obj: Dict[str, Any]) -> Optional[datetime]:
    value = safe_get(obj, "attributes", "updated_at", default=None)

    if not value:
        return None

    return parse_pco_datetime(value)

def pco_iter_pages_until_updated_at(
    path: str,
    auth: Tuple[str, str],
    since: datetime,
    params: Optional[Dict[str, str]] = None,
    per_page: int = 100,
    order_field: str = "updated_at",
) -> Iterator[Dict[str, Any]]:
    if params is None:
        params = {}

    per_page = max(1, min(int(per_page), 100))
    offset = 0

    since = since.astimezone(timezone.utc)

    with requests.Session() as session:
        while True:
            page_params = dict(params)
            page_params["per_page"] = str(per_page)
            page_params["offset"] = str(offset)

            # Newest first.
            page_params["order"] = f"-{order_field}"

            payload = pco_get(
                session=session,
                path=path,
                auth=auth,
                params=page_params,
            )

            data = payload.get("data", []) or []

            if not data:
                break

            kept = []

            for obj in data:
                updated_at = get_updated_at(obj)

                # If updated_at is missing, keep it rather than silently dropping it.
                if updated_at is None:
                    kept.append(obj)
                    continue

                # Since data is ordered newest -> oldest, this is where we stop.
                if updated_at < since:
                    if kept:
                        payload = dict(payload)
                        payload["data"] = kept
                        yield payload

                    return

                kept.append(obj)

            payload = dict(payload)
            payload["data"] = kept
            yield payload

            if len(data) < per_page:
                break

            offset += per_page

def build_field_row_from_datum(
    datum: Dict[str, Any],
    inc: Dict[Tuple[str, str], Dict[str, Any]],
) -> Optional[Tuple[str, Dict[str, Any]]]:
    cust = safe_get(datum, "relationships", "customizable", "data", default=None)

    if not isinstance(cust, dict):
        return None

    if cust.get("type") != "Person":
        return None

    person_id = cust.get("id")

    if not person_id:
        return None

    value = safe_get(datum, "attributes", "value")

    fd_ref = safe_get(datum, "relationships", "field_definition", "data", default={}) or {}
    fd_type = fd_ref.get("type")
    fd_id = fd_ref.get("id")

    field_definition = inc.get((fd_type, fd_id), {}) if fd_type and fd_id else {}
    fd_attr = field_definition.get("attributes", {}) or {}

    field_definition_name = fd_attr.get("name")
    field_definition_slug = fd_attr.get("slug")
    field_definition_data_type = fd_attr.get("data_type")

    tab_ref = safe_get(datum, "relationships", "tab", "data", default=None)

    if not isinstance(tab_ref, dict):
        tab_ref = safe_get(field_definition, "relationships", "tab", "data", default=None)

    tab_type = tab_ref.get("type") if isinstance(tab_ref, dict) else None
    tab_id = tab_ref.get("id") if isinstance(tab_ref, dict) else None

    tab_obj = inc.get((tab_type, tab_id), {}) if tab_type and tab_id else {}
    tab_attr = tab_obj.get("attributes", {}) or {}

    tab_name = tab_attr.get("name")

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
        "display_value": option_value if option_value not in (None, "") else value,
    }

    return person_id, row

def get_recent_people_objects(
    auth: Tuple[str, str],
    since: datetime,
    per_page: int = 100,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[Tuple[str, str], Dict[str, Any]]]]:
    people_by_id: Dict[str, Dict[str, Any]] = {}
    included_by_person_id: Dict[str, Dict[Tuple[str, str], Dict[str, Any]]] = {}

    params = {
        "include": PCO_PEOPLE_INCLUDE_PERSON,
    }

    for payload in pco_iter_pages_until_updated_at(
        "/people/v2/people",
        auth,
        since=since,
        params=params,
        per_page=per_page,
        order_field="updated_at",
    ):
        people = payload.get("data", []) or []
        inc_index = index_included(payload.get("included", []) or [])

        for person_obj in people:
            pid = person_obj.get("id")

            if not pid:
                continue

            people_by_id[pid] = person_obj
            included_by_person_id[pid] = inc_index

    return people_by_id, included_by_person_id

def get_recent_field_data_person_ids(
    auth: Tuple[str, str],
    since: datetime,
    per_page: int = 100,
) -> set[str]:
    person_ids: set[str] = set()

    params = {
        "include": PCO_PEOPLE_INCLUDE_FIELD_DATA,
    }

    for payload in pco_iter_pages_until_updated_at(
        "/people/v2/field_data",
        auth,
        since=since,
        params=params,
        per_page=per_page,
        order_field="updated_at",
    ):
        data = payload.get("data", []) or []

        for datum in data:
            cust = safe_get(datum, "relationships", "customizable", "data", default=None)

            if not isinstance(cust, dict):
                continue

            if cust.get("type") != "Person":
                continue

            pid = cust.get("id")

            if pid:
                person_ids.add(pid)

    return person_ids

def fetch_person_by_id(
    session: requests.Session,
    auth: Tuple[str, str],
    person_id: str,
) -> Tuple[Dict[str, Any], Dict[Tuple[str, str], Dict[str, Any]]]:
    payload = pco_get(
        session=session,
        path=f"/people/v2/people/{person_id}",
        auth=auth,
        params={
            "include": PCO_PEOPLE_INCLUDE_PERSON,
        },
    )

    person_obj = payload.get("data", {}) or {}
    inc_index = index_included(payload.get("included", []) or [])

    return person_obj, inc_index

def build_fields_for_person_ids(
    auth: Tuple[str, str],
    person_ids: set[str],
    per_page: int = 100,
) -> Dict[str, List[Dict[str, Any]]]:
    fields_by_person: Dict[str, List[Dict[str, Any]]] = {}

    with requests.Session() as session:
        for person_id in person_ids:
            offset = 0

            while True:
                payload = pco_get(
                    session=session,
                    path=f"/people/v2/people/{person_id}/field_data",
                    auth=auth,
                    params={
                        "include": PCO_PEOPLE_INCLUDE_FIELD_DATA,
                        "per_page": str(per_page),
                        "offset": str(offset),
                    },
                )

                data = payload.get("data", []) or []
                inc = index_included(payload.get("included", []) or [])

                for datum in data:
                    built = build_field_row_from_datum(datum, inc)

                    if not built:
                        continue

                    pid, row = built
                    fields_by_person.setdefault(pid, []).append(row)

                if len(data) < per_page:
                    break

                offset += per_page

    for pid, rows in fields_by_person.items():
        rows.sort(
            key=lambda r: (
                r.get("tab_name") or "",
                r.get("field_definition_name") or "",
            )
        )

    return fields_by_person





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

def extraction() -> Dict[str, Any]:
    tables: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]] = {}
    t0 = time.perf_counter()
    count = 0

    per_page = int(os.getenv("PCO_PEOPLE_PAGE_LIMIT", "100"))

    updated_since_raw = os.getenv("PCO_UPDATED_SINCE")

    if not updated_since_raw:
        raise ValueError("Missing required env var: PCO_UPDATED_SINCE")

    updated_since = parse_pco_datetime(updated_since_raw)

    auth = get_auth_from_env()

    try:
        # 1. Get people directly updated since cutoff.
        people_by_id, included_by_person_id = get_recent_people_objects(
            auth,
            since=updated_since,
            per_page=per_page,
        )

        # 2. Get people whose custom field data changed since cutoff.
        field_changed_person_ids = get_recent_field_data_person_ids(
            auth,
            since=updated_since,
            per_page=per_page,
        )

        # 3. Union all changed person ids.
        changed_person_ids = set(people_by_id.keys()) | field_changed_person_ids

        # 4. Fetch missing person objects for people found only through field_data changes.
        missing_person_ids = changed_person_ids - set(people_by_id.keys())

        with requests.Session() as session:
            for pid in missing_person_ids:
                person_obj, inc_index = fetch_person_by_id(session, auth, pid)

                if not person_obj:
                    continue

                people_by_id[pid] = person_obj
                included_by_person_id[pid] = inc_index

        # 5. Fetch full current custom fields only for changed people.
        fields_by_person = build_fields_for_person_ids(
            auth,
            changed_person_ids,
            per_page=100,
        )

        # 6. Build the same parsed structure as before.
        for pid in changed_person_ids:
            person_obj = people_by_id.get(pid)

            if not person_obj:
                continue

            processing = process_person_from_payload(
                person_obj,
                included_by_person_id.get(pid, {}),
                fields_by_person.get(pid, []),
            )

            tables.update(processing)
            count += 1

    finally:
        elapsed = time.perf_counter() - t0
        print(f"TOTAL UPDATED PEOPLE: {count} people in {elapsed:.2f}s")

    built = build_tables(tables)
    return built


def main() -> None:
    tables = extraction()

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

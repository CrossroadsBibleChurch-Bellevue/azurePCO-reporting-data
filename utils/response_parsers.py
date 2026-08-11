from typing import Any, Tuple, Optional, Dict, List


# This file contains various functions that are used to parse through the API JSON response. They are in this file so that this Azure Function is more modular and other API fetchers can in theory
# be implemented more easily. Also it makes the code more readable in general and not as long lol

def rel_id(resource: Dict[str, Any], relationship_name: str) -> Optional[str]:
    rel = resource.get("relationships", {}).get(relationship_name, {})
    data = rel.get("data")
    if isinstance(data, dict):
        return data.get("id")
    return None

def clean_text(s: Optional[str], max_len: int = 400) -> Optional[str]:
    if s is None:
        return None
    t = " ".join(str(s).split())
    if len(t) <= max_len:
        return t
    return t[: max_len - 3] + "..."

def _first_present(d: Dict[str, Any], keys: List[str]) -> Any:
    for k in keys:
        if k in d and d.get(k) is not None:
            return d.get(k)
    return None

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

# Function steps through given JSON nested structure to get the real data needed
def safe_get(dct: Dict[str, Any], *keys, default=None):
    # Get dictionary
    cur = dct
    # Step through each, key (relationships, event instance, data, etc)
    for k in keys:
        # If the key is found in the dictionary, then set cur to the data of that key, else return the default 
        # This way it will go through the nested JSON and find the values in the data segment, which is typically in relationships to resource_bookings, to data, to actual values
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]

    # Return found values
    return cur

def return_sorted(obj: Dict[str, Any]) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    # Sort by the key
    for k in sorted(obj.keys()):
        # Get value by key
        v = obj.get(k)
        data[k] = v
    return data

def safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def get_included_value(
    rels: Dict[str, Any],
    inc_index: Dict[Tuple[str, str], Dict[str, Any]],
    relationship_name: str,
) -> Optional[str]:
    ref = safe_get(rels, relationship_name, "data", default=None)

    if not isinstance(ref, dict):
        return None

    t = ref.get("type")
    i = ref.get("id")

    if not t or not i:
        return None

    obj = inc_index.get((t, i), {})
    attrs = obj.get("attributes", {}) or {}
    return attrs.get("value")

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
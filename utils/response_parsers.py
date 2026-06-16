from typing import Any, Tuple, Optional, Dict, List


# This file contains various functions that are used to parse through the API JSON response. They are in this file so that this Azure Function is more modular and other API fetchers can in theory
# be implemented more easily. Also it makes the code more readable in general and not as long lol

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
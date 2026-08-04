from typing import Dict, Any
from extractors.schemas.people_schemas import build_row_people
import re
import sys

def sanitize_schema_name(name: str) -> str:
    n = re.sub(r"[^A-Za-z0-9_]", "_", name)
    return n[:80]

# -----------------------------
# Upsert helpers
# -----------------------------
def strip_nones(row: Dict[str, Any]) -> Dict[str, Any]:
    # Omit nulls to avoid accidental clears unless desired.
    return {k: v for k, v in row.items() if v is not None}

def upsert_row(table: Dict[str, Dict[str, Any]], row: Dict[str, Any], pk: str = "id"):
    rid = row.get(pk)
    if rid is None:
        return
    if rid not in table:
        table[rid] = row
        return
    existing = table[rid]
    for k, v in row.items():
        if k == "cr0b4_unique_id" or k not in existing or existing[k] is None:
            existing[k] = v

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
                    #print(dict_level4.get("school"))
                    #print(dict_level4)
                    #sys.exit(0)
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
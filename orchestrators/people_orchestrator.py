import time

from extractors.people_extractor import extraction  # your extractor module name
from dataverse.dataverse_keys_and_upsert import ensure_keys_and_upsert_all
from database.loader import uploader
from utils.env_fetcher import DATAVERSE_ORG_URL


TABLE_MAP = {
    "address": "cr0b4_address",
    "core_attribute": "cr0b4_core_attribute",
    "custom_fields": "cr0b4_custom_fields",
    "custom_tabs": "cr0b4_custom_tabs",
    "custom_values": "cr0b4_custom_values",
    "emails": "cr0b4_emails",
    "household": "cr0b4_household",
    "phones": "cr0b4_phones",
}

KEY_PLAN = {
    "address": ["cr0b4_hash_id"],
    "core_attribute": ["cr0b4_person_id"],
    "custom_fields": ["cr0b4_hash_id"],
    "custom_tabs": ["cr0b4_hash_id"],
    "custom_values": ["cr0b4_hash_id"],
    "emails": ["cr0b4_hash_id"],
    "household": ["cr0b4_hash_id"],
    "phones": ["cr0b4_hash_id"],
}

def main(client):
    t0 = time.perf_counter()
    tables = extraction()
    t1 = time.perf_counter()

    """ensure_keys_and_upsert_all(
        dataverse_url=DATAVERSE_ORG_URL,
        tables=tables,
        table_map=TABLE_MAP,
        key_plan=KEY_PLAN,
        client=client,
    )"""
    uploader(tables)
    t2 = time.perf_counter()
    print(f"Extract seconds: {t1 - t0:.2f}")
    print(f"Upload seconds:  {t2 - t1:.2f}")
    print(f"Total seconds taken: {t2 - t0:.2f}")

if __name__ == "__main__":
    print("No client configured. Please configure that and then run this again")
    main(client=None)
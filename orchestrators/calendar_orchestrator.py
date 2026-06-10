import time

from extractors.calendar_extractor import extract_tables  # your extractor module name
from dataverse.dataverse_keys_and_upsert import ensure_keys_and_upsert_all
from dataverse.credentials_urls import DATAVERSE_ORG_URL

TABLE_MAP = {
    "owners": "cr548_ownersv4",
    "events": "cr548_eventsv4",
    "event_instances": "cr548_event_instancesv4",
    "event_times": "cr548_event_timesv4",
    "tags": "cr548_tagsv4",
    "tag_groups": "cr548_tag_groupsv4",
    "tag_groups_tag_maps": "cr548_tag_groups_tags_mapv4",
    "event_instance_tag_map": "cr548_event_instance_tag_map",
    "room_setups": "cr548_room_setupsv4",
    "rooms": "cr548_roomsv4",
    "resources": "cr548_resourcesv4",
    "event_resource_requests": "cr548_event_resource_requestsv4",
    "event_resource_answers": "cr548_event_resource_answersv4",
    "resource_bookings": "cr548_resource_bookingsv4",
    "schedule": "cr548_schedulev4",
}

KEY_PLAN = {
    "owners": ["cr0b4_unique_id"],
    "events": ["cr0b4_unique_id"],
    "event_instances": ["cr0b4_unique_id"],
    "event_times": ["cr0b4_unique_id"],
    "tags": ["cr0b4_unique_id"],
    "tag_groups": ["cr0b4_unique_id"],
    "tag_groups_tag_maps": ["cr0b4_unique_id"],
    "event_instance_tag_map": ["cr0b4_alt_key"],
    "room_setups": ["cr0b4_unique_id"],
    "rooms": ["cr0b4_unique_id"],
    "resources": ["cr0b4_unique_id"],
    "event_resource_requests": ["cr0b4_unique_id"],
    "event_resource_answers": ["cr0b4_unique_id"],
    "resource_bookings": ["cr0b4_unique_id"],
    "schedule": ["cr0b4_id"],
}

def main(client):
    t0 = time.perf_counter()
    tables = extract_tables()
    t1 = time.perf_counter()

    ensure_keys_and_upsert_all(
        dataverse_url=DATAVERSE_ORG_URL,
        tables=tables,
        table_map=TABLE_MAP,
        key_plan=KEY_PLAN,
        client=client,
    )
    t2 = time.perf_counter()
    print(f"Extract seconds: {t1 - t0:.2f}")
    print(f"Upload seconds:  {t2 - t1:.2f}")
    print(f"Total seconds taken: {t2 - t0:.2f}")

if __name__ == "__main__":
    print("No client configured. Please do that and then run this again")
    main(client=None)
from typing import Any, Callable, Dict

from utils.response_parsers import clean_text, _first_present
from utils.hasher import stable_hash_id

# This file contains all of the schemas for the various Dataverse Tables used. To edit a pre-existing table, merely go to the schema below and add, delete, or modify
# the schema as needed. If a new variable needs to be passed through, you will need to do that in the corresponding file and add that in.
# To add a schema, follow the other schemas below as an example and make sure that you pass through the right variables in the corresponding file that uses the schema

RowContext = Dict[str, Any]
FieldGetter = Callable[[RowContext], Any]
RowSchema = Dict[str, FieldGetter]


SCHEMAS: Dict[str, RowSchema] = {
    "address": {
        "cr0b4_hash_id": lambda c: stable_hash_id("address", c["person_id"], c["chunk"].get("zip")),
        "cr0b4_person_id": lambda c: c["person_id"],
        "cr0b4_city": lambda c: c["chunk"].get("city"),
        "cr0b4_country_code": lambda c: c["chunk"].get("country_code"),
        "cr0b4_country_name": lambda c: c["chunk"].get("country_name"),
        "cr0b4_location": lambda c: c["chunk"].get("location"),
        "cr0b4_primary": lambda c: str(c["chunk"].get("primary")),
        "cr0b4_state": lambda c: c["chunk"].get("state"),
        "cr0b4_street_line_1": lambda c: c["chunk"].get("street_line_1"),
        "cr0b4_street_line_2": lambda c: c["chunk"].get("street_line_2"),
        "cr0b4_zip": lambda c: c["chunk"].get("zip"),
    },

    "core_attribute": {
        "cr0b4_person_id": lambda c: c["person_id"],
        "cr0b4_anniversary": lambda c: c["chunk"].get("anniversary"),
        "cr0b4_birthdate": lambda c: c["chunk"].get("birthdate"),   
        "cr0b4_child": lambda c: c["chunk"].get("child"),
        "cr0b4_created_at": lambda c: c["chunk"].get("created_at"),
        "cr0b4_first_name": lambda c: c["chunk"].get("first_name"),
        "cr0b4_gender": lambda c: c["chunk"].get("gender"),
        "cr0b4_given_name": lambda c: c["chunk"].get("given_name"),
        "cr0b4_grade": lambda c: c["chunk"].get("grade"),
        "cr0b4_graduation_year": lambda c: c["chunk"].get("graduation_year"),
        "cr0b4_inactivated_at": lambda c: c["chunk"].get("inactivated_at"),
        "cr0b4_inactive_reason": lambda c: c["chunk"].get("inactive_reason"),
        "cr0b4_last_name": lambda c: c["chunk"].get("last_name"),
        "cr0b4_marital_status": lambda c: c["chunk"].get("marital_status"),
        "cr0b4_medical_notes": lambda c: c["chunk"].get("medical_notes"),
        "cr0b4_membership": lambda c: c["chunk"].get("membership"),
        "cr0b4_middle_name": lambda c: c["chunk"].get("middle_name"),
        "cr0b4_name": lambda c: c["chunk"].get("name"),
        "cr0b4_nickname": lambda c: c["chunk"].get("nickname"),
        "cr0b4_passed_background_check": lambda c: c["chunk"].get("passed_background_check"),
        "cr0b4_status": lambda c: c["chunk"].get("status"),
        "cr0b4_updated_at": lambda c: c["chunk"].get("updated_at"),
    },

    "custom_fields": {
        "cr0b4_hash_id": lambda c: stable_hash_id("custom_fields", c["chunk"].get("field_id")),
        "cr0b4_field_data_type": lambda c: c["chunk"].get("field_data_type"),
        "cr0b4_field_id": lambda c: c["chunk"].get("field_id"),
        "cr0b4_field_name": lambda c: c["chunk"].get("field_name"),
        "cr0b4_field_tab_id": lambda c: c["chunk"].get("field_tab_id"),
        "cr0b4_field_tab_name": lambda c: c["chunk"].get("field_tab_name"),
    },

    "custom_tabs": {
        "cr0b4_hash_id": lambda c: stable_hash_id("custom_tabs", c["chunk"].get("tab_id")),
        "cr0b4_tab_id": lambda c: c["chunk"].get("tab_id"),
        "cr0b4_tab_name": lambda c: c["chunk"].get("tab_name"),
    },

    "custom_values": {
        "cr0b4_hash_id": lambda c: stable_hash_id("custom_values", c["person_id"], c["chunk"].get("field_value"), stable_hash_id("custom_fields", c["chunk"].get("field_id"))),
        "cr0b4_custom_field_hash": lambda c: stable_hash_id("custom_fields", c["chunk"].get("field_id")),
        "cr0b4_value": lambda c: c["chunk"].get("field_value"),
        "cr0b4_person_id": lambda c: c["person_id"],
    },

    "emails": {
        "cr0b4_hash_id": lambda c: stable_hash_id("emails", c["person_id"], c["chunk"].get("address")),
        "cr0b4_people_id": lambda c: c["person_id"],
        "cr0b4_address": lambda c: c["chunk"].get("address"),
        "cr0b4_location": lambda c: c["chunk"].get("location"),
        "cr0b4_primary": lambda c: str(c["chunk"].get("primary")),
    },

    "household": {
        "cr0b4_hash_id": lambda c: stable_hash_id("households", c["person_id"], c["chunk"].get("household_id")),
        "cr0b4_person_id": lambda c: c["person_id"],
        "cr0b4_household_id": lambda c: c["chunk"].get("household_id"),
        "cr0b4_name": lambda c: None if c["chunk"].get("household_id") == "N/A" else c["chunk"].get("name"),
        "cr0b4_member_count": lambda c: None if c["chunk"].get("household_id") == "N/A" else str(c["chunk"].get("member_count")),
        "cr0b4_primary_contact_id": lambda c: None if c["chunk"].get("household_id") == "N/A" else c["chunk"].get("primary_contact_id"),
        "cr0b4_primary_contact_name": lambda c: None if c["chunk"].get("household_id") == "N/A" else c["chunk"].get("primary_contact_name"),
    },

    "phones": {
        "cr0b4_hash_id": lambda c: stable_hash_id("phones", c["person_id"], c["chunk"].get("number")),
        "cr0b4_people_id": lambda c: c["person_id"],
        "cr0b4_country_code": lambda c: c["chunk"].get("country_code"),
        "cr0b4_number": lambda c: c["chunk"].get("number"),
        "cr0b4_location": lambda c: c["chunk"].get("location"),
        "cr0b4_primary": lambda c: str(c["chunk"].get("primary")),
    },
}


def build_row_people(schema_name: str, context: RowContext) -> Dict[str, Any]:
    schema = SCHEMAS[schema_name]
    return {
        column_name: getter(context)
        for column_name, getter in schema.items()
    }
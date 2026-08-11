from typing import Any, Callable, Dict

from utils.response_parsers import clean_text, _first_present
from utils.hasher import stable_hash_id

# This file contains all of the schemas for the various Dataverse Tables used. To edit a pre-existing table, merely go to the schema below and add, delete, or modify
# the schema as needed. If a new variable needs to be passed through, you will need to do that in the corresponding file and add that in.
# To add a schema, follow the other schemas below as an example and make sure that you pass through the right variables in the corresponding file that uses the schema


# Need to change the hash for custom values since it won't properly be upserted if it is changed, since that would change the hash
# Might need to change other ones as well

RowContext = Dict[str, Any]
FieldGetter = Callable[[RowContext], Any]
RowSchema = Dict[str, FieldGetter]


SCHEMAS: Dict[str, RowSchema] = {
    "address": {
        "hash_id": lambda c: stable_hash_id("address", c["person_id"], c["chunk"].get("location")),
        "person_id": lambda c: c["person_id"],
        "city": lambda c: c["chunk"].get("city"),
        "country_code": lambda c: c["chunk"].get("country_code"),
        "country_name": lambda c: c["chunk"].get("country_name"),
        "location": lambda c: c["chunk"].get("location"),
        "primary": lambda c: str(c["chunk"].get("primary")),
        "state": lambda c: c["chunk"].get("state"),
        "street_line_1": lambda c: c["chunk"].get("street_line_1"),
        "street_line_2": lambda c: c["chunk"].get("street_line_2"),
        "zip": lambda c: c["chunk"].get("zip"),
    },

    "core_attribute": {
        "person_id": lambda c: c["person_id"],
        "anniversary": lambda c: str(c["chunk"].get("anniversary")),
        "birthdate": lambda c: c["chunk"].get("birthdate"),   
        "child": lambda c: c["chunk"].get("child"),
        "created_at": lambda c: c["chunk"].get("created_at"),
        "first_name": lambda c: str(c["chunk"].get("first_name")),
        "gender": lambda c: str(c["chunk"].get("gender")),
        "given_name": lambda c: str(c["chunk"].get("given_name")),
        "grade": lambda c: str(c["chunk"].get("grade")),
        "graduation_year": lambda c: str(c["chunk"].get("graduation_year")),
        "inactivated_at": lambda c: c["chunk"].get("inactivated_at"),
        "inactive_reason": lambda c: str(c["chunk"].get("inactive_reason")),
        "last_name": lambda c: str(c["chunk"].get("last_name")),
        "marital_status": lambda c: str(c["chunk"].get("marital_status")),
        "medical_notes": lambda c: str(c["chunk"].get("medical_notes")),
        "membership": lambda c: str(c["chunk"].get("membership")),
        "middle_name": lambda c: str(c["chunk"].get("middle_name")),
        "name": lambda c: str(c["chunk"].get("name")),
        "nickname": lambda c: str(c["chunk"].get("nickname")),
        "passed_background_check": lambda c: c["chunk"].get("passed_background_check"),
        "status": lambda c: str(c["chunk"].get("status")),
        "updated_at": lambda c: str(c["chunk"].get("updated_at")),
    },

    "custom_fields": {
        "hash_id": lambda c: stable_hash_id("custom_fields", c["chunk"].get("field_id")),
        "field_data_type": lambda c: c["chunk"].get("field_data_type"),
        "field_id": lambda c: c["chunk"].get("field_id"),
        "field_name": lambda c: c["chunk"].get("field_name"),
        "field_tab_id": lambda c: c["chunk"].get("field_tab_id"),
        "field_tab_name": lambda c: c["chunk"].get("field_tab_name"),
    },

    "custom_tabs": {
        "hash_id": lambda c: stable_hash_id("custom_tabs", c["chunk"].get("tab_id")),
        "tab_id": lambda c: c["chunk"].get("tab_id"),
        "tab_name": lambda c: c["chunk"].get("tab_name"),
    },

    "custom_values": {
        "hash_id": lambda c: stable_hash_id("custom_values", c["person_id"], stable_hash_id("custom_fields", c["chunk"].get("field_id"))),
        "custom_field_hash": lambda c: stable_hash_id("custom_fields", c["chunk"].get("field_id")),
        "value": lambda c: c["chunk"].get("field_value"),
        "person_id": lambda c: c["person_id"],
    },

    "emails": {
        "hash_id": lambda c: stable_hash_id("emails", c["person_id"], c["chunk"].get("location")),
        "people_id": lambda c: c["person_id"],
        "address": lambda c: c["chunk"].get("address"),
        "location": lambda c: c["chunk"].get("location"),
        "primary": lambda c: str(c["chunk"].get("primary")),
    },

    "household": {
        "hash_id": lambda c: stable_hash_id("households", c["person_id"]),
        "person_id": lambda c: c["person_id"],
        "household_id": lambda c: c["chunk"].get("household_id"),
        "name": lambda c: None if c["chunk"].get("household_id") == "N/A" else c["chunk"].get("name"),
        "member_count": lambda c: None if c["chunk"].get("household_id") == "N/A" else str(c["chunk"].get("member_count")),
        "primary_contact_id": lambda c: None if c["chunk"].get("household_id") == "N/A" else c["chunk"].get("primary_contact_id"),
        "primary_contact_name": lambda c: None if c["chunk"].get("household_id") == "N/A" else c["chunk"].get("primary_contact_name"),
    },

    "phones": {
        "hash_id": lambda c: stable_hash_id("phones", c["person_id"], c["chunk"].get("location")),
        "people_id": lambda c: c["person_id"],
        "country_code": lambda c: c["chunk"].get("country_code"),
        "number": lambda c: c["chunk"].get("number"),
        "location": lambda c: c["chunk"].get("location"),
        "primary": lambda c: str(c["chunk"].get("primary")),
    },
}


def build_row_people(schema_name: str, context: RowContext) -> Dict[str, Any]:
    schema = SCHEMAS[schema_name]
    return {
        column_name: getter(context)
        for column_name, getter in schema.items()
    }
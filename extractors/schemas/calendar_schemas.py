from typing import Any, Callable, Dict

from utils.response_parsers import clean_text, _first_present
from utils.hasher import stable_hash_id

# This file contains all of the schemas for the various Dataverse Tables used. To edit a pre-existing table, merely go to the schema below and add, delete, or modify
# the schema as needed. If a new variable needs to be passed through, you will need to do that in the corresponding file and add that in.
# To add a schema, follow the other schemas below as an example and make sure that you pass through the right variables in the corresponding file that uses the schema

RowContext = Dict[str, Any]
FieldGetter = Callable[[RowContext], Any]
RowSchema = Dict[str, FieldGetter]


def safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


SCHEMAS: Dict[str, RowSchema] = {
    "tag_groups": {
        "cr0b4_unique_id": lambda c: stable_hash_id("tag_group", c["tg_id"]),
        "cr548_id": lambda c: c["tg_id"],
        "cr548_name1": lambda c: c["tg_attr"].get("name"),
        "cr548_required": lambda c: c["tg_attr"].get("required"),
        "cr548_created_at": lambda c: c["tg_attr"].get("created_at"),
        "cr548_updated_at": lambda c: c["tg_attr"].get("updated_at"),
    },

    "tags": {
        "cr0b4_unique_id": lambda c: stable_hash_id("tag", c["tag_id"]),
        "cr548_id": lambda c: c["tag_id"],
        "cr548_name": lambda c: c["t_attr"].get("name"),
        "cr548_color": lambda c: c["t_attr"].get("color"),
        "cr548_church_center_category": lambda c: c["t_attr"].get("church_center_category"),
        "cr548_position": lambda c: safe_int(c["t_attr"].get("position")),
        "cr548_created_at": lambda c: c["t_attr"].get("created_at"),
        "cr548_updated_at": lambda c: c["t_attr"].get("updated_at"),
    },

    "tag_groups_tag_maps": {
        "cr0b4_unique_id": lambda c: stable_hash_id("tag_groups_tag_maps", c["tag_id"], c["tg_id"]),
        "cr548_tagid": lambda c: c["tag_id"],
        "cr548_tag_groupid": lambda c: c["tg_id"],
    },

    "owners": {
        "cr0b4_unique_id": lambda c: stable_hash_id("owner", c["owner_id"]),
        "cr548_id": lambda c: c["owner_id"],
        "cr548_first_name": lambda c: c["owner_attr"].get("first_name"),
        "cr548_last_name": lambda c: c["owner_attr"].get("last_name"),
    },

    "events": {
        "cr0b4_unique_id": lambda c: stable_hash_id("event", c["ev_id"]),
        "cr548_id": lambda c: c["ev_id"],
        "cr548_name": lambda c: c["ev_attr"].get("name"),
        "cr548_summary": lambda c: clean_text(c["ev_attr"].get("summary")),
        "cr548_description": lambda c: clean_text(c["ev_attr"].get("description")),
        "cr548_registration_url": lambda c: c["ev_attr"].get("registration_url"),
        "cr548_approval_status": lambda c: c["ev_attr"].get("approval_status"),
        "cr548_visible_in_church_center": lambda c: c["ev_attr"].get("visible_in_church_center"),
        "cr548_featured": lambda c: c["ev_attr"].get("featured"),
        "cr548_image_url": lambda c: c["ev_attr"].get("image_url"),
        "cr548_created_at": lambda c: c["ev_attr"].get("created_at"),
        "cr548_updated_at": lambda c: c["ev_attr"].get("updated_at"),
        "cr548_ownerid": lambda c: None if c.get("owner_id") == "null_person" else c.get("owner_id"),
        "cr548_percent_approved": lambda c: _first_present(c["ev_attr"], ["percent_approved", "percentApproved"]),
        "cr548_percent_rejected": lambda c: _first_present(c["ev_attr"], ["percent_rejected", "percentRejected"]),
    },

    "event_instances": {
        "cr0b4_unique_id": lambda c: stable_hash_id("event_instance", c["inst_id"]),
        "cr548_id": lambda c: c["inst_id"],
        "cr548_eventid": lambda c: c["ev_id"],
        "cr548_location": lambda c: c["attr"].get("location"),
        "cr548_all_day_event": lambda c: c["attr"].get("all_day_event"),
        "cr548_church_center_url": lambda c: c["attr"].get("church_center_url"),
        "cr548_starts_at": lambda c: c["attr"].get("starts_at"),
        "cr548_ends_at": lambda c: c["attr"].get("ends_at"),
        "cr548_published_starts_at": lambda c: c["attr"].get("published_starts_at"),
        "cr548_published_ends_at": lambda c: c["attr"].get("published_ends_at"),
        "cr548_created_at": lambda c: c["attr"].get("created_at"),
        "cr548_updated_at": lambda c: c["attr"].get("updated_at"),
        "cr548_recurrence": lambda c: c["attr"].get("recurrence"),
        "cr548_recurrence_description1": lambda c: c["attr"].get("recurrence_description"),
        "cr548_compact_recurrence_description": lambda c: c["attr"].get("compact_recurrence_description"),
        "cr548_day_of_week": lambda c: c.get("day_of_week"),
    },

    "resources": {
        "cr0b4_unique_id": lambda c: stable_hash_id("resource", c["resource_id"]),
        "cr548_id": lambda c: c["resource_id"],
        "cr548_name1": lambda c: c["res_attr"].get("name"),
        "cr548_path_name": lambda c: c["res_attr"].get("path_name"),
        "cr548_kind": lambda c: c["res_attr"].get("kind"),
        "cr548_description": lambda c: clean_text(c["res_attr"].get("description")),
        "cr548_serial_number": lambda c: c["res_attr"].get("serial_number"),
        "cr548_home_location": lambda c: c["res_attr"].get("home_location"),
        "cr548_quantity": lambda c: c["res_attr"].get("quantity"),
        "cr548_url": lambda c: c["res_attr"].get("url"),
        "cr548_expires_at": lambda c: c["res_attr"].get("expires_at"),
        "cr548_created_at": lambda c: c["res_attr"].get("created_at"),
        "cr548_updated_at": lambda c: c["res_attr"].get("updated_at"),
    },

    "rooms": {
        "cr0b4_unique_id": lambda c: stable_hash_id("room", c["room_id"]),
        "cr548_id": lambda c: c["room_id"],
        "cr548_name1": lambda c: c["r_attr"].get("name"),
        "cr548_path_name": lambda c: c["r_attr"].get("path_name"),
        "cr548_kind": lambda c: c["r_attr"].get("kind"),
        "cr548_description": lambda c: clean_text(c["r_attr"].get("description")),
        "cr548_serial_number": lambda c: c["r_attr"].get("serial_number"),
        "cr548_home_location": lambda c: c["r_attr"].get("home_location"),
        "cr548_quantity": lambda c: c["r_attr"].get("quantity"),
        "cr548_url": lambda c: c["r_attr"].get("url"),
        "cr548_expires_at": lambda c: c["r_attr"].get("expires_at"),
        "cr548_created_at": lambda c: c["r_attr"].get("created_at"),
        "cr548_updated_at": lambda c: c["r_attr"].get("updated_at"),
    },

    "event_times": {
        "cr0b4_unique_id": lambda c: stable_hash_id("event_time", c["et_id"]),
        "cr548_id": lambda c: c["et_id"],
        "cr548_eventid": lambda c: c["ev_id"],
        "cr548_name": lambda c: c["et_attr"].get("name"),
        "cr548_starts_at": lambda c: c["et_attr"].get("starts_at"),
        "cr548_ends_at": lambda c: c["et_attr"].get("ends_at"),
        "cr548_visible_on_kiosks": lambda c: c["et_attr"].get("visible_on_kiosks"),
        "cr548_visible_on_widget_and_ical": lambda c: c["et_attr"].get("visible_on_widget_and_ical"),
    },

    "event_instance_tag_map": {
        "cr0b4_alt_key": lambda c: stable_hash_id("event_instance_tag_map", c["inst_id"], c["tag_id"]),
        "cr548_event_instanceid": lambda c: c["inst_id"],
        "cr548_tagid": lambda c: c["tag_id"],
    },

    "resource_bookings": {
        "cr0b4_unique_id": lambda c: stable_hash_id("resource_booking", c["rb_id"]),
        "cr548_id": lambda c: c["rb_id"],
        "cr548_eventid": lambda c: c["ev_id"],
        "cr548_event_instanceid": lambda c: c["inst_id"],
        "cr548_resourceid": lambda c: c["res_id"],
        "cr548_event_resource_requestid": lambda c: c["req_id"],
        "cr548_quantity": lambda c: c["rb_attr"].get("quantity"),
        "cr548_starts_at": lambda c: c["rb_attr"].get("starts_at"),
        "cr548_ends_at": lambda c: c["rb_attr"].get("ends_at"),
        "cr548_created_at": lambda c: c["rb_attr"].get("created_at"),
        "cr548_updated_at": lambda c: c["rb_attr"].get("updated_at"),
    },

    "room_setups": {
        "cr0b4_unique_id": lambda c: stable_hash_id("room_setup", c["rs_id"]),
        "cr548_id": lambda c: c["rs_id"],
        "cr548_name": lambda c: c["rs_attr"].get("name"),
        "cr548_description": lambda c: clean_text(c["rs_attr"].get("description")),
        "cr548_diagram_url": lambda c: c["rs_attr"].get("diagram_url") or c["rs_attr"].get("diagramUrl"),
        "cr548_created_at": lambda c: c["rs_attr"].get("created_at"),
        "cr548_updated_at": lambda c: c["rs_attr"].get("updated_at"),
    },

    "event_resource_requests": {
        "cr0b4_unique_id": lambda c: stable_hash_id("event_resource_request", c["req_id"]),
        "cr548_id": lambda c: c["req_id"],
        "cr548_eventid": lambda c: c["req_event_id"],
        "cr548_resourceid": lambda c: c["req_resource_id"],
        "cr548_room_setupid": lambda c: c["rs_id"],
        "cr548_notes": lambda c: clean_text(c["req_attr"].get("notes")),
        "cr548_approval_sent": lambda c: c["req_attr"].get("approval_sent"),
        "cr548_approval_status": lambda c: c["req_attr"].get("approval_status"),
        "cr548_quantity": lambda c: c["req_attr"].get("quantity"),
        "cr548_created_byid": lambda c: c["created_by_id"],
        "cr548_updated_byid": lambda c: c["updated_by_id"],
        "cr548_created_at": lambda c: c["req_attr"].get("created_at"),
        "cr548_updated_at": lambda c: c["req_attr"].get("updated_at"),
        "cr548_related_errid": lambda c: _first_present(c["req_attr"], ["related_event_resource_request_id", "related_errid"]),
    },

    "event_resource_answers": {
        "cr0b4_unique_id": lambda c: stable_hash_id("event_resource_answers", c["ans_id"]),
        "cr548_id": lambda c: c["ans_id"],
        "cr548_event_resource_requestid": lambda c: c["req_id"],
        "cr548_resource_question_id": lambda c: c["q_id"],
        "cr548_question_text": lambda c: c["question_text"],
        "cr548_answer1": lambda c: c["answer_text"],
        "cr548_created_at": lambda c: c["ans_attr"].get("created_at"),
        "cr548_updated_at": lambda c: c["ans_attr"].get("updated_at"),
    },

    "schedule": {
        "cr0b4_id": lambda c: stable_hash_id("schedule", c["rb_id"], c["req_id"], c["inst_id"], c["ans"], c["ques"]),
        "cr548_assignee": lambda c: None,
        "cr548_completion_status": lambda c: None,
        "cr548_event_instanceid": lambda c: c["inst_id"],
        "cr548_event_resource_answeranswer": lambda c: c["ans"],
        "cr548_event_resource_answerquestion": lambda c: c["ques"],
        "cr548_event_resource_requestid": lambda c: c["req_id"],
        "cr548_eventid": lambda c: c["ev_id"],
        "cr548_eventname": lambda c: c["ev_attr"].get("name") if c["ev_attr"] else None,
        "cr548_notes": lambda c: clean_text(c["req_attr"].get("notes")),
        "cr548_ownerfirst_name": lambda c: (c["owners"].get(c["owner_id"], {}) or {}).get("cr548_first_name") if c["owner_id"] else None,
        "cr548_ownerid": lambda c: c["owner_id"],
        "cr548_ownerlast_name": lambda c: (c["owners"].get(c["owner_id"], {}) or {}).get("cr548_last_name") if c["owner_id"] else None,
        "cr548_resource_bookingcreated_at": lambda c: c["rb_attr"].get("created_at"),
        "cr548_resource_bookingends_at": lambda c: c["rb_attr"].get("ends_at"),
        "cr548_resource_bookingid": lambda c: c["rb_id"],
        "cr548_resource_bookingstarts_at": lambda c: c["rb_attr"].get("starts_at"),
        "cr548_resource_bookingupdated_at": lambda c: c["rb_attr"].get("updated_at"),
        "cr548_resourceid": lambda c: c["res_id"],
        "cr548_room_setupid": lambda c: c["rs_id"],
        "cr548_room_setupname": lambda c: (c["room_setups"].get(c["rs_id"], {}) or {}).get("cr548_name") if c["rs_id"] else None,
        "cr548_roomname": lambda c: (c["rooms"].get(c["res_id"], {}) or {}).get("cr548_name1") if c["res_id"] else None,
    }
}


def build_row(schema_name: str, context: RowContext) -> Dict[str, Any]:
    schema = SCHEMAS[schema_name]
    return {
        column_name: getter(context)
        for column_name, getter in schema.items()
    }
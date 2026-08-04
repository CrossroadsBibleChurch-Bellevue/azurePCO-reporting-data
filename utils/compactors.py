from typing import Optional, Dict, Any
from utils.response_parsers import rel_id


def compact_person(person: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not person:
        return None

    attrs = person.get("attributes", {})
    return {
        "id": person.get("id"),
        "first_name": attrs.get("first_name"),
        "last_name": attrs.get("last_name"),
        "avatar_url": attrs.get("avatar_url"),
        "permissions": attrs.get("permissions"),
    }


def compact_group(group: Dict[str, Any]) -> Dict[str, Any]:
    attrs = group.get("attributes", {})
    return {
        "id": group.get("id"),
        "name": attrs.get("name"),
        "description": attrs.get("description_as_plain_text") or attrs.get("description"),
        "archived_at": attrs.get("archived_at"),
        "created_at": attrs.get("created_at"),
        "memberships_count": attrs.get("memberships_count"),
        "schedule": attrs.get("schedule"),
        "listed": attrs.get("listed"),
        "events_listed": attrs.get("events_listed"),
        "events_visibility": attrs.get("events_visibility"),
        "location_type_preference": attrs.get("location_type_preference"),
        "virtual_location_url": attrs.get("virtual_location_url"),
        "public_church_center_web_url": attrs.get("public_church_center_web_url"),
        "group_type_id": rel_id(group, "group_type"),
        "location_id": rel_id(group, "location"),
    }


def compact_group_type(group_type: Dict[str, Any]) -> Dict[str, Any]:
    attrs = group_type.get("attributes", {})

    return {
        "id": group_type.get("id"),
        "name": attrs.get("name"),
        "church_center_visible": attrs.get("church_center_visible"),
    }

def compact_membership(
    membership: Dict[str, Any],
    included_people_by_id: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    attrs = membership.get("attributes", {})
    person_id = rel_id(membership, "person")

    return {
        "id": membership.get("id"),
        "group_id": rel_id(membership, "group"),
        "person_id": person_id,
        "role": attrs.get("role"),
        "joined_at": attrs.get("joined_at"),
        "left_at": attrs.get("left_at"),
        "person": compact_person(
            included_people_by_id.get(person_id)
        ),
    }


def compact_event(event: Dict[str, Any]) -> Dict[str, Any]:
    attrs = event.get("attributes", {})

    return {
        "id": event.get("id"),
        "group_id": rel_id(event, "group"),
        "parent_event_id": rel_id(event, "repeating_event") or event.get("id"),
        "repeating_event_id": rel_id(event, "repeating_event"),
        "name": attrs.get("name"),
        "description": attrs.get("description"),
        "starts_at": attrs.get("starts_at"),
        "ends_at": attrs.get("ends_at"),
        "canceled": attrs.get("canceled"),
        "canceled_at": attrs.get("canceled_at"),
        "multi_day": attrs.get("multi_day"),
        "repeating": attrs.get("repeating"),
        "location_type_preference": attrs.get("location_type_preference"),
        "virtual_location_url": attrs.get("virtual_location_url"),
        "visitors_count": attrs.get("visitors_count"),
        "attendance_requests_enabled": attrs.get(
            "attendance_requests_enabled"
        ),
        "automated_reminder_enabled": attrs.get(
            "automated_reminder_enabled"
        ),
        "reminders_sent": attrs.get("reminders_sent"),
        "reminders_sent_at": attrs.get("reminders_sent_at"),
        "attendance_submitter_id": rel_id(
            event,
            "attendance_submitter",
        ),
        "location_id": rel_id(event, "location"),
    }

def compact_tag_group(
    tag_group: Dict[str, Any],
) -> Dict[str, Any]:
    attrs = tag_group.get("attributes", {})

    return {
        "tag_group_id": tag_group.get("id"),
        "name": attrs.get("name"),
        "position": attrs.get("position"),
        "display_publicly": attrs.get("display_publicly"),
        "multiple_options_enabled": attrs.get(
            "multiple_options_enabled"
        ),
    }


def compact_tag(
    tag: Dict[str, Any],
    fallback_tag_group_id: Optional[str] = None,
) -> Dict[str, Any]:
    attrs = tag.get("attributes", {})

    return {
        "tag_id": tag.get("id"),
        "tag_group_id": (
            rel_id(tag, "tag_group")
            or fallback_tag_group_id
        ),
        "name": attrs.get("name"),
        "position": attrs.get("position"),
    }
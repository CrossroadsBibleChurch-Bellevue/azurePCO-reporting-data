from typing import List, Dict, Any
from datetime import datetime, timezone
from collections import defaultdict

from utils.time_functions import now_utc, parse_pco_datetime
from utils.hasher import stable_hash_id

# This file is used by both groups extractors to take the raw data from the API and then parse and turn into rows/tables that can be used by the loader to input data into the database.

def build_output(
    groups: List[Dict[str, Any]],
    group_types: List[Dict[str, Any]],
    memberships_by_group: Dict[str, List[Dict[str, Any]]],
    events: List[Dict[str, Any]],
    attendance_by_event: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    events_by_group = defaultdict(list)
    group_types_by_id = {
        group_type["id"]: group_type
        for group_type in group_types
        if group_type.get("id")
    }

    for event in events:
        attendance = attendance_by_event.get(event["id"], {})
        event["attendance"] = attendance
        events_by_group[event.get("group_id")].append(event)

    output_groups = []

    for group in groups:
        group_id = group["id"]
        group_type_id = group.get("group_type_id")
        group["group_type"] = group_types_by_id.get(group_type_id)
        memberships = memberships_by_group.get(group_id, [])
        group_events = events_by_group.get(group_id, [])

        event_attendance_rates = [
            event.get("attendance", {}).get("attendance_rate")
            for event in group_events
            if event.get("attendance", {}).get("attendance_rate") is not None
        ]

        group["memberships"] = memberships
        group["events"] = group_events
        group["analytics"] = {
            "membership_count_from_memberships_endpoint": len(memberships),
            "event_count_returned": len(group_events),
            "average_event_attendance_rate": (
                round(sum(event_attendance_rates) / len(event_attendance_rates), 4)
                if event_attendance_rates
                else None
            ),
            "total_attended_count_across_returned_events": sum(
                event.get("attendance", {}).get("attended_count", 0)
                for event in group_events
            ),
            "total_attendance_records_across_returned_events": sum(
                event.get("attendance", {}).get("attendance_record_count", 0)
                for event in group_events
            ),
        }

        output_groups.append(group)

    return {
        "generated_at": now_utc().isoformat(),
        "summary": {
            "group_type_count": len(group_types),
            "group_count": len(output_groups),
            "event_count": len(events),
            "attendance_event_count": len(attendance_by_event),
        },
        "group_types": group_types,
        "groups": output_groups,
    }


def build_group_types_table_rows(
    output: Dict[str, Any],
) -> List[Dict[str, Any]]:
    groups_per_type: Dict[str, int] = defaultdict(int)

    for group in output.get("groups", []):
        group_type_id = group.get("group_type_id")

        if group_type_id:
            groups_per_type[group_type_id] += 1

    rows = []

    for group_type in output.get("group_types", []):
        group_type_id = group_type.get("id")
        if group_type_id == "unique":
            group_type_id = -1

        rows.append(
            {
                "group_type_id": group_type_id,
                "group_type_name": group_type.get("name"),
                "church_center_visible": group_type.get(
                    "church_center_visible"
                ),
                "group_count": groups_per_type.get(group_type_id, 0),
            }
        )

    return rows


def build_group_overview_table_rows(output: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []

    for group in output["groups"]:
        analytics = group.get("analytics", {})
        memberships = group.get("memberships", [])
        events = group.get("events", [])

        attended_total = analytics.get("total_attended_count_across_returned_events") or 0
        attendance_records_total = analytics.get("total_attendance_records_across_returned_events") or 0

        rows.append(
            {
                "group_id": group.get("id"),
                "group_name": group.get("name"),
                "group_type_id": group.get("group_type_id"),
                "member_count": len(memberships),
                "pco_memberships_count": group.get("memberships_count"),
                "event_count": len(events),
                "total_attended": attended_total,
                "total_attendance_records": attendance_records_total,
                "created_at": group.get("created_at"),
                "archived_at": group.get("archived_at"),
            }
        )

    return rows

def build_group_members_table_rows(output: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []

    for group in output["groups"]:
        group_id = group.get("id")

        for membership in group.get("memberships", []):

            rows.append(
                {
                    "group_id": group_id,
                    "membership_id": membership.get("id"),
                    "person_id": membership.get("person_id"),
                    "role": membership.get("role"),
                    "joined_at": membership.get("joined_at"),
                }
            )

    return rows

def build_group_memberships_table_rows(
    output: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Build one row per membership returned by Planning Center.

    Important:
    The Groups memberships endpoint normally represents current
    memberships. Former memberships that have been removed from Planning
    Center may no longer be returned by the API.
    """

    rows = []

    for group in output.get("groups", []):
        group_id = group.get("id")

        for membership in group.get("memberships", []):
            rows.append(
                {
                    "membership_id": membership.get("id"),
                    "group_id": group_id,
                    "person_id": membership.get("person_id"),
                    "joined_at": membership.get("joined_at"),
                    "left_at": membership.get("left_at"),
                    "role": membership.get("role"),
                }
            )

    return sorted(
        rows,
        key=lambda row: (
            row.get("group_id") or "",
            row.get("person_id") or "",
            row.get("joined_at") or "",
        ),
    )

def build_event_instances_table_rows(
    events: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    rows = []

    for event in events:
        rows.append(
            {
                "event_instance_id": event.get("id"),
                "event_id": event.get("parent_event_id"),
                "group_id": event.get("group_id"),
                "name": event.get("name"),
                "starts_at": event.get("starts_at"),
                "ends_at": event.get("ends_at"),
                "canceled": event.get("canceled"),
                "visitors_count": event.get("visitors_count"),
                "location_id": event.get("location_id"),
                "classification": event.get(
                    "event_time_classification"
                ),
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            row.get("group_id") or "",
            parse_pco_datetime(row.get("starts_at"))
            or datetime.max.replace(tzinfo=timezone.utc),
            row.get("event_instance_id") or "",
        ),
    )


def build_events_table_rows(
    event_instances: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    events_by_id: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for instance in event_instances:
        event_id = instance.get("parent_event_id")

        if event_id:
            events_by_id[event_id].append(instance)

    rows = []

    for event_id, instances in events_by_id.items():
        sorted_instances = sorted(
            instances,
            key=lambda instance: (
                parse_pco_datetime(instance.get("starts_at"))
                or datetime.max.replace(tzinfo=timezone.utc)
            ),
        )

        first_instance = sorted_instances[0]
        last_instance = sorted_instances[-1]
        repeating_event_id = first_instance.get(
            "repeating_event_id"
        )

        rows.append(
            {
                "event_id": event_id,
                "pco_repeating_event_id": repeating_event_id,
                "group_id": first_instance.get("group_id"),
                "name": first_instance.get("name"),
                "repeating": repeating_event_id is not None,
                "instance_count": len(sorted_instances),
                "location_type_preference": first_instance.get(
                    "location_type_preference"
                ),
                "location_id": first_instance.get("location_id"),
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            row.get("group_id") or "",
            parse_pco_datetime(
                row.get("first_instance_starts_at")
            )
            or datetime.max.replace(tzinfo=timezone.utc),
            row.get("event_id") or "",
        ),
    )


def build_tag_groups_table_rows(
    tag_groups: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    return [
        {
            "tag_group_id": tag_group.get("tag_group_id"),
            "name": tag_group.get("name"),
            "display_publicly": tag_group.get(
                "display_publicly"
            ),
            "multiple_options_enabled": tag_group.get(
                "multiple_options_enabled"
            ),
        }
        for tag_group in tag_groups
    ]


def build_tags_table_rows(
    tags: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    return [
        {
            "tag_id": tag.get("tag_id"),
            "tag_group_id": tag.get("tag_group_id"),
            "name": tag.get("name"),
        }
        for tag in tags
    ]


def build_group_tags_table_rows(
    group_tags: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    seen = set()
    rows = []

    for group_tag in group_tags:
        key = (
            group_tag.get("group_id"),
            group_tag.get("tag_id"),
        )

        if key in seen:
            continue

        seen.add(key)

        rows.append(
            {
                "hash_id": stable_hash_id("group_tags", group_tag.get("group_id"), group_tag.get("tag_id")),
                "group_id": group_tag.get("group_id"),
                "tag_id": group_tag.get("tag_id"),
            }
        )

    return rows


def build_all_attendance_table_rows(
    output: Dict[str, Any],
) -> List[Dict[str, Any]]:
    rows = []

    for group in output.get("groups", []):
        group_id = group.get("id")

        memberships = group.get("memberships", [])

        members_by_person_id = {
            membership.get("person_id"): membership
            for membership in memberships
            if membership.get("person_id")
        }

        for event in group.get("events", []):
            attendance = event.get("attendance", {})
            attendance_records = attendance.get(
                "all_attendance_records",
                [],
            )

            attendance_by_person_id = {
                record.get("person_id"): record
                for record in attendance_records
                if record.get("person_id")
            }

            # Include:
            # 1. Current group members, even if they have no attendance record.
            # 2. People with an attendance record who are not current members.
            all_person_ids = (
                set(members_by_person_id.keys())
                | set(attendance_by_person_id.keys())
            )

            for person_id in sorted(all_person_ids):
                membership = members_by_person_id.get(person_id)
                attendance_record = attendance_by_person_id.get(person_id)

                person = None

                if attendance_record:
                    person = attendance_record.get("person")

                if not person and membership:
                    person = membership.get("person")

                attendance_record_exists = attendance_record is not None

                attended = (
                    attendance_record.get("attended")
                    if attendance_record_exists
                    else None
                )

                rows.append(
                    {
                        "hash_id": stable_hash_id("event_attendance", event.get("id"), person_id),
                        "group_id": group_id,
                        "event_instance_id": event.get("id"),
                        "person_id": person_id,
                        "current_group_member": membership is not None,
                        "membership_id": (
                            membership.get("id")
                            if membership
                            else None
                        ),
                        "membership_role": (
                            membership.get("role")
                            if membership
                            else ""
                        ),
                        "attendance_id": (
                            attendance_record.get("id")
                            if attendance_record
                            else None
                        ),
                        "attendance_role": (
                            attendance_record.get("role")
                            if attendance_record
                            else ""
                        ),
                        "attended": attended,
                        "attendance_record_exists": (
                            attendance_record_exists
                        ),
                    }
                )

    return sorted(
        rows,
        key=lambda row: (
            row.get("group_name") or "",
            parse_pco_datetime(row.get("starts_at"))
            or datetime.max.replace(tzinfo=timezone.utc),
            row.get("last_name") or "",
            row.get("first_name") or "",
            row.get("person_id") or "",
        ),
    )
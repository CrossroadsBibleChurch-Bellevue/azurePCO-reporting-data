from typing import Any
from collections import defaultdict

from utils.check_ins_shared import Config, attrs, rel_id, resource_date, safe_int, date_in_range

def build_checkin_event_rows(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for event in events:
        event_attrs = attrs(event)

        rows.append(
            {
                "CheckInEventID": str(event.get("id")),
                "Name": event_attrs.get("name"),
                "Frequency": event_attrs.get("frequency"),
                "ArchivedAt": event_attrs.get("archived_at"),
                "CreatedAt": event_attrs.get("created_at"),
                "UpdatedAt": event_attrs.get("updated_at"),
                "IntegrationKey": event_attrs.get("integration_key"),
            }
        )

    return rows

def build_checkin_event_instance_rows(
    index: dict[tuple[str, str], dict[str, Any]],
    config: Config,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    event_periods = [
        resource
        for resource in index.values()
        if resource.get("type") == "EventPeriod"
    ]

    event_periods.sort(
        key=lambda resource: (
            attrs(resource).get("starts_at") or "",
            str(resource.get("id") or ""),
        )
    )

    for event_period in event_periods:
        event_period_id = str(event_period.get("id"))
        period_attrs = attrs(event_period)

        period_date = resource_date(
            event_period,
            "starts_at",
            "ends_at",
            "created_at",
        )

        if not date_in_range(
            period_date,
            config.start_date,
            config.end_date,
        ):
            continue

        event_id = rel_id(event_period, "event")

        rows.append(
            {
                "CheckInEventInstanceID": event_period_id,
                "CheckInEventID": event_id,
                "StartsAt": period_attrs.get("starts_at"),
                "EndsAt": period_attrs.get("ends_at"),
                "RegularCount": period_attrs.get("regular_count"),
                "GuestCount": period_attrs.get("guest_count"),
                "VolunteerCount": period_attrs.get("volunteer_count"),
                "TotalCount": (
                    safe_int(period_attrs.get("regular_count"))
                    + safe_int(period_attrs.get("guest_count"))
                    + safe_int(period_attrs.get("volunteer_count"))
                ),
                "Note": period_attrs.get("note"),
                "CreatedAt": period_attrs.get("created_at"),
                "UpdatedAt": period_attrs.get("updated_at"),
            }
        )

    return rows

def build_checkin_event_attendance_rows(
    checkins: list[dict[str, Any]],
    index: dict[tuple[str, str], dict[str, Any]],
    config: Config,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    check_in_times_by_checkin: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for resource in index.values():
        if resource.get("type") != "CheckInTime":
            continue

        check_in_id = rel_id(resource, "check_in")

        if check_in_id:
            check_in_times_by_checkin[check_in_id].append(resource)

    for checkin in checkins:
        check_in_id = str(checkin.get("id"))
        checkin_attrs = attrs(checkin)

        checkin_date = resource_date(
            checkin,
            "confirmed_at",
            "created_at",
            "updated_at",
        )

        if not date_in_range(
            checkin_date,
            config.start_date,
            config.end_date,
        ):
            continue

        person_id = rel_id(checkin, "person")
        event_period_id = rel_id(checkin, "event_period")

        event_period = (
            index.get(("EventPeriod", event_period_id))
            if event_period_id
            else None
        )

        event_id = rel_id(event_period, "event")

        if not event_id:
            event_id = rel_id(checkin, "event")

        person = (
            index.get(("Person", person_id))
            if person_id
            else None
        )

        check_in_times = check_in_times_by_checkin.get(check_in_id)

        # Preserve the CheckIn even if PCO returned no CheckInTime.
        if not check_in_times:
            check_in_times = [None]

        for check_in_time in check_in_times:
            check_in_time_id = (
                str(check_in_time.get("id"))
                if check_in_time
                else None
            )

            event_time_id = (
                rel_id(check_in_time, "event_time")
                if check_in_time
                else None
            )

            location_id = (
                rel_id(check_in_time, "location")
                if check_in_time
                else None
            )

            location = (
                index.get(("Location", location_id))
                if location_id
                else None
            )

            check_in_time_attrs = attrs(check_in_time)

            rows.append(
                {
                    "CheckInEventAttendanceID": (
                        check_in_time_id or f"checkin-{check_in_id}"
                    ),
                    "CheckInID": check_in_id,
                    "CheckInTimeID": check_in_time_id,
                    "CheckInEventID": event_id,
                    "CheckInEventInstanceID": event_period_id,
                    "EventTimeID": event_time_id,

                    "PersonID": person_id,
                    "PersonName": attrs(person).get("name"),
                    "FirstName": (
                        attrs(person).get("first_name")
                        or checkin_attrs.get("first_name")
                    ),
                    "LastName": (
                        attrs(person).get("last_name")
                        or checkin_attrs.get("last_name")
                    ),
                    "Grade": attrs(person).get("grade"),
                    "Gender": attrs(person).get("gender"),
                    "Child": attrs(person).get("child"),

                    "AttendanceKind": checkin_attrs.get("kind"),
                    "CheckInNumber": checkin_attrs.get("number"),
                    "CheckedInAt": (
                        checkin_attrs.get("confirmed_at")
                        or checkin_attrs.get("created_at")
                    ),
                    "CheckedOutAt": checkin_attrs.get("checked_out_at"),
                    "OneTimeGuest": checkin_attrs.get("one_time_guest"),
                    "FirstTime": checkin_attrs.get("first_time"),
                    "SecurityCode": checkin_attrs.get("security_code"),

                    "LocationID": location_id,
                    "LocationName": attrs(location).get("name"),
                    "LocationKind": attrs(location).get("kind"),

                    "CheckInTimeKind": check_in_time_attrs.get("kind"),
                    "HasValidated": check_in_time_attrs.get("has_validated"),

                    "CreatedAt": checkin_attrs.get("created_at"),
                    "UpdatedAt": checkin_attrs.get("updated_at"),
                }
            )

    return rows

def build_headcount_rows(
    index: dict[tuple[str, str], dict[str, Any]],
    config: Config,
) -> list[dict[str, Any]]:
    """
    Build one row per PCO Headcount resource.

    Row grain:
        One Headcount per EventTime and AttendanceType.
    """
    rows: list[dict[str, Any]] = []

    headcounts = [
        resource
        for resource in index.values()
        if resource.get("type") == "Headcount"
    ]

    for headcount in headcounts:
        headcount_id = str(headcount.get("id"))
        headcount_attrs = attrs(headcount)

        event_time_id = rel_id(headcount, "event_time")
        attendance_type_id = rel_id(headcount, "attendance_type")

        event_time = (
            index.get(("EventTime", event_time_id))
            if event_time_id
            else None
        )

        attendance_type = (
            index.get(("AttendanceType", attendance_type_id))
            if attendance_type_id
            else None
        )

        # Headcount itself does not contain the event-period date.
        # Apply the date filter using its related EventTime.
        event_time_date = (
            resource_date(
                event_time,
                "starts_at",
                "shows_at",
                "created_at",
            )
            if event_time
            else None
        )

        if not date_in_range(
            event_time_date,
            config.start_date,
            config.end_date,
        ):
            continue

        checkin_event_id = (
            rel_id(event_time, "event")
            if event_time
            else None
        )

        checkin_event_instance_id = (
            rel_id(event_time, "event_period")
            if event_time
            else None
        )

        # Fallback when the EventTime does not directly expose its Event.
        if not checkin_event_id and checkin_event_instance_id:
            event_period = index.get(
                ("EventPeriod", checkin_event_instance_id)
            )

            checkin_event_id = rel_id(
                event_period,
                "event",
            )

        rows.append(
            {
                "HeadcountID": headcount_id,
                "CheckInEventID": checkin_event_id,
                "CheckInEventInstanceID": checkin_event_instance_id,
                "EventTimeID": event_time_id,
                "AttendanceTypeID": attendance_type_id,
                "AttendanceTypeName": attrs(attendance_type).get("name"),
                "AttendanceTypeColor": attrs(attendance_type).get("color"),
                "AttendanceTypeLimit": attrs(attendance_type).get("limit"),
                "Total": headcount_attrs.get("total"),
                "CreatedAt": headcount_attrs.get("created_at"),
                "UpdatedAt": headcount_attrs.get("updated_at"),
            }
        )

    rows.sort(
        key=lambda row: (
            str(row.get("CheckInEventID") or ""),
            str(row.get("CheckInEventInstanceID") or ""),
            str(row.get("EventTimeID") or ""),
            str(row.get("AttendanceTypeID") or ""),
            str(row.get("HeadcountID") or ""),
        )
    )

    return rows


def build_event_time_rows(
    index: dict[tuple[str, str], dict[str, Any]],
    config: Config,
) -> list[dict[str, Any]]:
    """
    Build one row per PCO EventTime resource.

    Row grain:
        One selectable check-in time within a CheckInEventInstance.
    """
    rows: list[dict[str, Any]] = []

    event_times = [
        resource
        for resource in index.values()
        if resource.get("type") == "EventTime"
    ]

    for event_time in event_times:
        event_time_id = str(event_time.get("id"))
        event_time_attrs = attrs(event_time)

        event_time_date = resource_date(
            event_time,
            "starts_at",
            "shows_at",
            "created_at",
        )

        if not date_in_range(
            event_time_date,
            config.start_date,
            config.end_date,
        ):
            continue

        checkin_event_id = rel_id(
            event_time,
            "event",
        )

        checkin_event_instance_id = rel_id(
            event_time,
            "event_period",
        )

        # Some included EventTime resources may not expose the Event
        # directly, so get it through the related EventPeriod.
        if not checkin_event_id and checkin_event_instance_id:
            event_period = index.get(
                ("EventPeriod", checkin_event_instance_id)
            )

            checkin_event_id = rel_id(
                event_period,
                "event",
            )

        rows.append(
            {
                "EventTimeID": event_time_id,
                "CheckInEventID": checkin_event_id,
                "CheckInEventInstanceID": checkin_event_instance_id,
                "Name": event_time_attrs.get("name"),
                "StartsAt": event_time_attrs.get("starts_at"),
                "ShowsAt": event_time_attrs.get("shows_at"),
                "HidesAt": event_time_attrs.get("hides_at"),
                "DayOfWeek": event_time_attrs.get("day_of_week"),
                "Hour": event_time_attrs.get("hour"),
                "Minute": event_time_attrs.get("minute"),
                "RegularCount": event_time_attrs.get("regular_count"),
                "GuestCount": event_time_attrs.get("guest_count"),
                "VolunteerCount": event_time_attrs.get("volunteer_count"),
                "TotalCount": event_time_attrs.get("total_count"),
                "CreatedAt": event_time_attrs.get("created_at"),
                "UpdatedAt": event_time_attrs.get("updated_at"),
            }
        )

    rows.sort(
        key=lambda row: (
            str(row.get("CheckInEventID") or ""),
            str(row.get("CheckInEventInstanceID") or ""),
            str(row.get("StartsAt") or row.get("ShowsAt") or ""),
            str(row.get("EventTimeID") or ""),
        )
    )

    return rows
import pyodbc

from database.converters import normalize_optional_datetime

TABLE_CONFIGS = {
    "address": {
        "target_table": "dbo.PCO_People_Address",
        "staging_table": "dbo.STAGING_PCO_People_Address",
        "key_columns": ["HashId"],
        "required_source_keys": [
            "hash_id"
        ],
        "column_map": {
            "HashId": "hash_id",
            "PersonID": "person_id",
            "City": "city",
            "CountryCode": "country_code",
            "CountryName": "country_name",
            "Location": "location",
            "PrimaryLocation": "primary",
            "State": "state",
            "StreetLine1": "street_line_1",
            "StreetLine2": "street_line_2",
            "Zip": "zip"
        },
    },

    
    "core_attribute": {
        "target_table": "dbo.PCO_People_Core",
        "staging_table": "dbo.STAGING_PCO_People_Core",
        "key_columns": ["PersonID"],
        "required_source_keys": [
            "person_id"
        ],
        "column_map": {
            "PersonID": "person_id",
            "BirthDate": "birthdate",
            "Child": "child",
            "CreatedAt": "created_at",
            "CurrentStatus": "status",
            "FirstName": "first_name",
            "FullName": "name",
            "Gender": "gender",
            "GivenName": "given_name",
            "Grade": "grade",
            "GraduationYear": "graduation_year",
            "InactivatedAt": "inactivated_at",
            "InactiveReason": "inactive_reason",
            "LastName": "last_name",
            "MaritalStatus": "marital_status",
            "MedicalNotes": "medical_notes",
            "Membership": "membership",
            "MiddleName": "middle_name",
            "NickName": "nickname",
            "PassedBackgroundCheck": "passed_background_check",
            "UpdatedAt": "updated_at",
        },
    },


    "custom_fields": {
        "target_table": "dbo.PCO_People_CustomFields",
        "staging_table": "dbo.STAGING_PCO_People_CustomFields",
        "key_columns": ["HashId"],
        "required_source_keys": [
            "hash_id"
        ],
        "column_map": {
            "HashId": "hash_id",
            "FieldDataType": "field_data_type",
            "FieldId": "field_id",
            "FieldName": "field_name",
            "FieldTabId": "field_tab_id",
            "FieldTabName": "field_tab_name",
        },
    },

    "custom_tabs": {
        "target_table": "dbo.PCO_People_CustomTabs",
        "staging_table": "dbo.STAGING_PCO_People_CustomTabs",
        "key_columns": ["HashId"],
        "required_source_keys": [
            "hash_id"
        ],
        "column_map": {
            "HashId": "hash_id",
            "TabId": "tab_id",
            "TabName": "tab_name",
        },
    },

    "custom_values": {
        "target_table": "dbo.PCO_People_CustomValue",
        "staging_table": "dbo.STAGING_PCO_People_CustomValue",
        "key_columns": ["HashId"],
        "required_source_keys": [
            "hash_id"
        ],
        "column_map": {
            "HashId": "hash_id",
            "PersonID": "person_id",
            "CustomFieldHash": "custom_field_hash",
            "CustomValue": "value",
            
        },
    },

    "emails": {
        "target_table": "dbo.PCO_People_Email",
        "staging_table": "dbo.STAGING_PCO_People_Email",
        "key_columns": ["HashId"],
        "required_source_keys": [
            "hash_id"
        ],
        "column_map": {
            "HashId": "hash_id",
            "PersonID": "people_id",
            "EmailAddress": "address",
            "Location": "location",
            "PrimaryLocation": "primary",
        },
    },

    "household": {
        "target_table": "dbo.PCO_People_Household",
        "staging_table": "dbo.STAGING_PCO_People_Household",
        "key_columns": ["HashId"],
        "required_source_keys": [
            "hash_id"
        ],
        "column_map": {
            "HashId": "hash_id",
            "PersonID": "person_id",
            "HouseholdId": "household_id",
            "HouseholdName": "name",
            "MemberCount": "member_count",
            "PrimaryContactId": "primary_contact_id",
            "PrimaryContactName": "primary_contact_name",
        },
    },

    "phones": {
        "target_table": "dbo.PCO_People_Phone",
        "staging_table": "dbo.STAGING_PCO_People_Phone",
        "key_columns": ["HashId"],
        "required_source_keys": [
            "hash_id"
        ],
        "column_map": {
            "HashId": "hash_id",
            "PersonID": "people_id",
            "CountryCode": "country_code",
            "PhoneNumber": "number",
            "Location": "location",
            "PrimaryLocation": "primary",
        },
    },
    

    "group_overview": {
        "target_table": "dbo.PCO_Groups_overview",
        "staging_table": "dbo.STAGING_PCO_Groups_overview",
        "key_columns": ["GroupID"],
        "required_source_keys": [
            "group_id"
        ],
        "column_map": {
            "GroupID": "group_id",
            "GroupName": "group_name",
            "GroupTypeID": "group_type_id",
            "MemberCount": "member_count",
            "PCOMembershipCount": "pco_memberships_count",
            "EventCount": "event_count",
            "TotalAttended": "total_attended",
            "TotalAttendanceRecords": "total_attendance_records",
            "CreatedAt": "created_at",
            "ArchivedAt": "archived_at",
        },
    },

    "group_types": {
        "target_table": "dbo.PCO_Groups_types",
        "staging_table": "dbo.STAGING_PCO_Groups_types",
        "key_columns": ["GroupTypeID"],
        "required_source_keys": [
            "group_type_id"
        ],
        "column_map": {
            "GroupTypeID": "group_type_id",
            "GroupTypeName": "group_type_name",
            "ChurchCenterVisible": "church_center_visible",
            "GroupCount": "group_count",
        },
    },

    "group_tags": {
        "target_table": "dbo.PCO_Groups_group_tags",
        "staging_table": "dbo.STAGING_PCO_Groups_group_tags",
        "key_columns": ["HashID"],
        "required_source_keys": [
            "hash_id"
        ],
        "column_map": {
            "HashID": "hash_id",
            "GroupID": "group_id",
            "TagID": "tag_id",
        },
    },

    "tags": {
        "target_table": "dbo.PCO_Groups_tags",
        "staging_table": "dbo.STAGING_PCO_Groups_tags",
        "key_columns": ["TagID"],
        "required_source_keys": [
            "tag_id"
        ],
        "column_map": {
            "TagID": "tag_id",
            "TagGroupID": "tag_group_id",
            "TagName": "name",
        },
    },

    "tag_groups": {
        "target_table": "dbo.PCO_Groups_tag_groups",
        "staging_table": "dbo.STAGING_PCO_Groups_tag_groups",
        "key_columns": ["TagGroupID"],
        "required_source_keys": [
            "tag_group_id"
        ],
        "column_map": {
            "TagGroupID": "tag_group_id",
            "TagGroupName": "name",
            "DisplayPublicly": "display_publicly",
            "MultipleOptionsEnabled": "multiple_options_enabled",
        },
    },

    "events": {
        "target_table": "dbo.PCO_Groups_Events",
        "staging_table": "dbo.STAGING_PCO_Groups_Events",
        "key_columns": ["EventID"],
        "required_source_keys": [
            "event_id"
        ],
        "column_map": {
            "EventID": "event_id",
            "PCORepeatingEventID": "pco_repeating_event_id",
            "GroupID": "group_id",
            "EventName": "name",
            "Repeating": "repeating",
            "InstanceCount": "instance_count",
            "LocationTypePreference": "location_type_preference",
            "LocationID": "location_id"
        },
    },

    "event_instances": {
        "target_table": "dbo.PCO_Groups_Event_Instances",
        "staging_table": "dbo.STAGING_PCO_Groups_Event_Instances",
        "key_columns": ["EventInstanceID"],
        "required_source_keys": [
            "event_instance_id"
        ],
        "column_map": {
            "EventInstanceID": "event_instance_id",
            "EventID": "event_id",
            "EventName": "name",
            "StartsAt": "starts_at",
            "EndsAt": "ends_at",
            "Canceled": "canceled",
            "VisitorsCount": "visitors_count",
            "Classification": "classification",
            "LocationID": "location_id"
        },
    },

    "event_attendances": {
        "target_table": "dbo.PCO_Groups_Event_Attendances",
        "staging_table": "dbo.STAGING_PCO_Groups_Event_Attendances",
        "key_columns": ["HashID"],
        "required_source_keys": [
            "hash_id"
        ],
        "column_map": {
            "HashID": "hash_id",
            "EventInstanceID": "event_instance_id",
            "PersonID": "person_id",
            "CurrentGroupMember": "current_group_member",
            "MembershipRole": "membership_role",
            "AttendanceID": "attendance_id",
            "AttendanceRole": "attendance_role",
            "Attended": "attended",
            "AttendanceRecordExists": "attendance_record_exists"
        },
    },

    "group_members": {
        "target_table": "dbo.PCO_Groups_Members",
        "staging_table": "dbo.STAGING_PCO_Groups_Members",
        "key_columns": ["MembershipID"],
        "required_source_keys": [
            "membership_id"
        ],
        "column_map": {
            "MembershipID": "membership_id",
            "PersonID": "person_id",
            "GroupID": "group_id",
            "Role": "role",
            "JoinedAt": "joined_at"
        },
    },

    "group_members_history": {
        "target_table": "dbo.PCO_Groups_Members_History",
        "staging_table": "dbo.STAGING_PCO_Groups_Members_History",
        "key_columns": ["MembershipID"],
        "required_source_keys": [
            "membership_id"
        ],
        "column_map": {
            "MembershipID": "membership_id",
            "PersonID": "person_id",
            "GroupID": "group_id",
            "Role": "role",
            "JoinedAt": "joined_at",
            "LeftAt": "left_at"
        },
    },



    "checkins_events": {
        "target_table": "dbo.PCO_Check_Ins_Events",
        "staging_table": "dbo.STAGING_PCO_Check_Ins_Events",
        "key_columns": ["CheckInEventID"],
        "required_source_keys": [
            "CheckInEventID"
        ],
        "column_map": {
            "CheckInEventID": "CheckInEventID",
            "EventName": "Name",
            "Frequency": "Frequency",
            "ArchivedAt": "ArchivedAt",
            "CreatedAt": "CreatedAt",
            "UpdatedAt": "UpdatedAt",
        },

        "input_sizes": [
            (pyodbc.SQL_BIGINT, 0, 0),
            (pyodbc.SQL_WVARCHAR, 255, 0),
            (pyodbc.SQL_WVARCHAR, 100, 0),
            (pyodbc.SQL_TYPE_TIMESTAMP, 0, 7),
            (pyodbc.SQL_TYPE_TIMESTAMP, 0, 7),
            (pyodbc.SQL_TYPE_TIMESTAMP, 0, 7),
        ],

        "fast_executemany": True,
    },

    "checkins_event_instances": {
        "target_table": "dbo.PCO_Check_Ins_Event_Instances",
        "staging_table": "dbo.STAGING_PCO_Check_Ins_Event_Instances",
        "key_columns": ["CheckInEventInstanceID"],
        "required_source_keys": [
            "CheckInEventInstanceID"
        ],
        "column_map": {
            "CheckInEventInstanceID": "CheckInEventInstanceID",
            "CheckInEventID": "CheckInEventID",
            "StartsAt": "StartsAt",
            "EndsAt": "EndsAt",
            "RegularCount": "RegularCount",
            "GuestCount": "GuestCount",
            "VolunteerCount": "VolunteerCount",
            "TotalCount": "TotalCount",
            "Note": "Note",
            "CreatedAt": "CreatedAt",
            "UpdatedAt": "UpdatedAt",
        },

        "fast_executemany": False,
    },

    "checkins_attendance": {
        "target_table": "dbo.PCO_Check_Ins_Attendance",
        "staging_table": "dbo.STAGING_PCO_Check_Ins_Attendance",
        "key_columns": ["CheckInEventAttendanceID"],
        "required_source_keys": [
            "CheckInEventAttendanceID"
        ],
        "column_map": {
            "CheckInEventAttendanceID": "CheckInEventAttendanceID",
            "CheckInID": "CheckInID",
            "CheckInTimeID": "CheckInTimeID",
            "CheckInEventID": "CheckInEventID",
            "CheckInEventInstanceID": "CheckInEventInstanceID",
            "EventTimeID": "EventTimeID",
            "PersonID": "PersonID",
            "AttendanceKind": "AttendanceKind",
            "CheckInTime": "CheckInTime",
            "CheckOutTime": "CheckOutTime",
            "LocationID": "LocationID",
        },

        "converters": {
            "CheckInTime": normalize_optional_datetime,
            "CheckOutTime": normalize_optional_datetime,
        },
    },

    "checkins_eventtimes": {
        "target_table": "dbo.PCO_Check_Ins_Event_Times",
        "staging_table": "dbo.STAGING_PCO_Check_Ins_Event_Times",
        "key_columns": ["EventTimeID"],
        "required_source_keys": [
            "EventTimeID"
        ],
        "column_map": {
            "EventTimeID": "EventTimeID",
            "CheckInEventID": "CheckInEventID",
            "CheckInEventInstanceID": "CheckInEventInstanceID",
            "Name": "Name",
            "StartsAt": "StartsAt",
            "ShowsAt": "ShowsAt",
            "HidesAt": "HidesAt",
            "RegularCount": "RegularCount",
            "GuestCount": "GuestCount",
            "VolunteerCount": "VolunteerCount",
            "TotalCount": "TotalCount",
        },

        "converters": {
            "StartsAt": normalize_optional_datetime,
            "ShowsAt": normalize_optional_datetime,
            "HidesAt": normalize_optional_datetime,
        },
    },

    "headcounts": {
        "target_table": "dbo.PCO_Check_Ins_Headcounts",
        "staging_table": "dbo.STAGING_PCO_Check_Ins_Headcounts",
        "key_columns": ["HeadcountID"],
        "required_source_keys": [
            "HeadcountID"
        ],
        "column_map": {
            "HeadcountID": "HeadcountID",
            "CheckInEventID": "CheckInEventID",
            "CheckInEventInstanceID": "CheckInEventInstanceID",
            "EventTimeID": "EventTimeID",
            "AttendanceTypeID": "AttendanceTypeID",
            "AttendanceTypeName": "AttendanceTypeName",
            "Total": "Total",
            "CreatedAt": "CreatedAt",
            "UpdatedAt": "UpdatedAt",
        },
    },

    # Example pattern for another table:
    #
    # "groups": {
    #     "target_table": "dbo.PCO_Groups",
    #     "staging_table": "dbo.PCO_Groups_Staging",
    #     "key_columns": ["PersonID"],
    #     "required_source_keys": [
    #         "group_id"
    #     ],
    #     "column_map": {
    #         "PersonID": "group_id",
    #         "Name": "name",
    #         "CreatedAt": "created_at",
    #         "UpdatedAt": "updated_at",
    #     },
    # },
}
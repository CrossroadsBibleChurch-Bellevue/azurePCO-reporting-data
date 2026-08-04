from datetime import datetime

month = datetime.now().strftime("%B")
year = datetime.now().year
snapshot = f"{month}_{year}"


TABLE_CONFIGS = {
    "address": {
        "target_table": "dbo.PCO_People_Address",
        "staging_table": "dbo.PCO_People_Address_Staging",
        "key_columns": ["HashId"],
        "required_source_keys": [
            "cr0b4_hash_id"
        ],
        "column_map": {
            "HashId": "cr0b4_hash_id",
            "PlanningCenterId": "cr0b4_person_id",
            "City": "cr0b4_city",
            "CountryCode": "cr0b4_country_code",
            "CountryName": "cr0b4_country_name",
            "Location": "cr0b4_location",
            "PrimaryLocation": "cr0b4_primary",
            "State": "cr0b4_state",
            "StreetLine1": "cr0b4_street_line_1",
            "StreetLine2": "cr0b4_street_line_2",
            "Zip": "cr0b4_zip"
        },
    },

    
    "core_attribute": {
        "target_table": "dbo.PCO_People_Core",
        "staging_table": "dbo.PCO_People_Core_Staging",
        "key_columns": ["PlanningCenterId"],
        "required_source_keys": [
            "cr0b4_person_id"
        ],
        "column_map": {
            "PlanningCenterId": "cr0b4_person_id",
            "BirthDate": "cr0b4_birthdate",
            "Child": "cr0b4_child",
            "CreatedAt": "cr0b4_created_at",
            "CurrentStatus": "cr0b4_status",
            "FirstName": "cr0b4_first_name",
            "FullName": "cr0b4_name",
            "Gender": "cr0b4_gender",
            "GivenName": "cr0b4_given_name",
            "Grade": "cr0b4_grade",
            "GraduationYear": "cr0b4_graduation_year",
            "InactivatedAt": "cr0b4_inactivated_at",
            "InactiveReason": "cr0b4_inactive_reason",
            "LastName": "cr0b4_last_name",
            "MaritalStatus": "cr0b4_marital_status",
            "MedicalNotes": "cr0b4_medical_notes",
            "Membership": "cr0b4_membership",
            "MiddleName": "cr0b4_middle_name",
            "NickName": "cr0b4_nickname",
            "PassedBackgroundCheck": "cr0b4_passed_background_check",
            "UpdatedAt": "cr0b4_updated_at",
        },
    },


    "custom_fields": {
        "target_table": "dbo.PCO_People_CustomFields",
        "staging_table": "dbo.PCO_People_CustomFields_Staging",
        "key_columns": ["HashId"],
        "required_source_keys": [
            "cr0b4_hash_id"
        ],
        "column_map": {
            "HashId": "cr0b4_hash_id",
            "FieldDataType": "cr0b4_field_data_type",
            "FieldId": "cr0b4_field_id",
            "FieldName": "cr0b4_field_name",
            "FieldTabId": "cr0b4_field_tab_id",
            "FieldTabName": "cr0b4_field_tab_name",
        },
    },

    "custom_tabs": {
        "target_table": "dbo.PCO_People_CustomTabs",
        "staging_table": "dbo.PCO_People_CustomTabs_Staging",
        "key_columns": ["HashId"],
        "required_source_keys": [
            "cr0b4_hash_id"
        ],
        "column_map": {
            "HashId": "cr0b4_hash_id",
            "TabId": "cr0b4_tab_id",
            "TabName": "cr0b4_tab_name",
        },
    },

    "custom_values": {
        "target_table": "dbo.PCO_People_CustomValue",
        "staging_table": "dbo.PCO_People_CustomValue_Staging",
        "key_columns": ["HashId"],
        "required_source_keys": [
            "cr0b4_hash_id"
        ],
        "column_map": {
            "HashId": "cr0b4_hash_id",
            "PlanningCenterId": "cr0b4_person_id",
            "CustomFieldHash": "cr0b4_custom_field_hash",
            "CustomValue": "cr0b4_value",
            
        },
    },

    "emails": {
        "target_table": "dbo.PCO_People_Email",
        "staging_table": "dbo.PCO_People_Email_Staging",
        "key_columns": ["HashId"],
        "required_source_keys": [
            "cr0b4_hash_id"
        ],
        "column_map": {
            "HashId": "cr0b4_hash_id",
            "PlanningCenterId": "cr0b4_people_id",
            "EmailAddress": "cr0b4_address",
            "Location": "cr0b4_location",
            "PrimaryLocation": "cr0b4_primary",
        },
    },

    "household": {
        "target_table": "dbo.PCO_People_Household",
        "staging_table": "dbo.PCO_People_Household_Staging",
        "key_columns": ["HashId"],
        "required_source_keys": [
            "cr0b4_hash_id"
        ],
        "column_map": {
            "HashId": "cr0b4_hash_id",
            "PlanningCenterId": "cr0b4_person_id",
            "HouseholdId": "cr0b4_household_id",
            "HouseholdName": "cr0b4_name",
            "MemberCount": "cr0b4_member_count",
            "PrimaryContactId": "cr0b4_primary_contact_id",
            "PrimaryContactName": "cr0b4_primary_contact_name",
        },
    },

    "phones": {
        "target_table": "dbo.PCO_People_Phone",
        "staging_table": "dbo.PCO_People_Phone_Staging",
        "key_columns": ["HashId"],
        "required_source_keys": [
            "cr0b4_hash_id"
        ],
        "column_map": {
            "HashId": "cr0b4_hash_id",
            "PlanningCenterId": "cr0b4_people_id",
            "CountryCode": "cr0b4_country_code",
            "PhoneNumber": "cr0b4_number",
            "Location": "cr0b4_location",
            "PrimaryLocation": "cr0b4_primary",
        },
    },
    

    "group_overview": {
        "target_table": "dbo.PCO_GROUPS_overview",
        "staging_table": "dbo.PCO_GROUPS_overview_STAGING",
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
        "target_table": "dbo.PCO_GROUPS_types",
        "staging_table": "dbo.PCO_GROUPS_types_STAGING",
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
        "target_table": "dbo.PCO_GROUPS_group_tags",
        "staging_table": "dbo.PCO_GROUPS_group_tags_STAGING",
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
        "target_table": "dbo.PCO_GROUPS_tags",
        "staging_table": "dbo.PCO_GROUPS_tags_STAGING",
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
        "target_table": "dbo.PCO_GROUPS_tag_groups",
        "staging_table": "dbo.PCO_GROUPS_tag_groups_STAGING",
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
        "target_table": "dbo.PCO_GROUPS_Events",
        "staging_table": "dbo.PCO_GROUPS_Events_Staging",
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
        "target_table": "dbo.PCO_GROUPS_Event_Instances",
        "staging_table": "dbo.PCO_GROUPS_Event_Instances_Staging",
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
        "target_table": "dbo.PCO_GROUPS_Event_Attendances",
        "staging_table": "dbo.PCO_GROUPS_Event_Attendances_Staging",
        "key_columns": ["HashID"],
        "required_source_keys": [
            "hash_id"
        ],
        "column_map": {
            "HashID": "hash_id",
            "EventInstanceID": "event_instance_id",
            "EventName": "name",
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
        "target_table": "dbo.PCO_GROUPS_Members",
        "staging_table": "dbo.PCO_GROUPS_Members_Staging",
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
        "target_table": "dbo.PCO_GROUPS_Members_History",
        "staging_table": "dbo.PCO_GROUPS_Members_History_Staging",
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

    "headcounts": {
        "target_table": "dbo.PCO_Check_Ins_Headcounts",
        "staging_table": "dbo.PCO_Check_Ins_Headcounts_STAGING",
        "key_columns": ["HashId"],
        "required_source_keys": [
            "hash_id"
        ],
        "column_map": {
            "HashId": "hash_id",
            "EventID": "event_id",
            "EventName": "event_name",
            "EventTimeID": "event_time_id",
            "HeadCountID": "headcount_id",
            "HeadCountTotal": "headcount_total",
            "AttendanceTypeName": "attendance_type_name",
            "AttendanceTypeID": "attendance_type_id",
            "CreatedAt": "created_at",
            "UpdatedAt": "updated_at",
        },
    },

    "checkins_events": {
        "target_table": "dbo.PCO_Check_Ins_Events",
        "staging_table": "dbo.PCO_Check_Ins_Event_STAGING",
        "key_columns": ["HashId"],
        "required_source_keys": [
            "hash_id"
        ],
        "column_map": {
            "HashId": "hash_id",
            "EventID": "event_id",
            "EventName": "event_name",
            "EventDate": "event_date",
            "EventTime": "event_time",
            "HeadCountID": "headcount_id",
            "ArchivedAt": "archived_at",
            "CheckInCount": "check_in_count",
            "CreatedAt": "created_at",
            "UpdatedAt": "updated_at",
        },
    },

    "checkins_event_location": {
        "target_table": "dbo.PCO_Check_Ins_Event_Locations",
        "staging_table": "dbo.PCO_Check_Ins_Event_Locations_STAGING",
        "key_columns": ["HashId"],
        "required_source_keys": [
            "hash_id"
        ],
        "column_map": {
            "HashId": "hash_id",
            "EventID": "event_id",
            "EventName": "event_name",
            "EventTimeID": "event_time_id",
            "EventTime": "event_time",
            "LocationEventTimeID": "location_event_time_id",
            "LocationID": "location_id",
            "LocationName": "location_name",
            "AttendersCount": "attenders_count",
            "CreatedAt": "created_at",
            "UpdatedAt": "updated_at",
        },
    },

    "checkins_checkins": {
        "target_table": "dbo.PCO_Check_Ins_Check_Ins",
        "staging_table": "dbo.PCO_Check_Ins_Check_Ins_STAGING",
        "key_columns": ["HashId"],
        "required_source_keys": [
            "hash_id"
        ],
        "column_map": {
            "HashId": "hash_id",
            "CheckInID": "check_in_id",
            "PersonName": "person_id",
            "PersonID": "person_id",
            "EventID": "event_id",
            "EventName": "event_name",
            "CheckInTime": "check_time_in",
            "CheckOutTime": "check_time_out",
            "CheckInKind": "check_in_kind",
            "EventPeriodID": "event_period_id",
            "EventTimeID": "event_time_id",
            "CreatedAt": "created_at",
            "UpdatedAt": "updated_at",
        },
    },


    # Example pattern for another table:
    #
    # "groups": {
    #     "target_table": "dbo.PCO_Groups",
    #     "staging_table": "dbo.PCO_Groups_Staging",
    #     "key_columns": ["PlanningCenterId"],
    #     "required_source_keys": [
    #         "cr0b4_group_id"
    #     ],
    #     "column_map": {
    #         "PlanningCenterId": "cr0b4_group_id",
    #         "Name": "cr0b4_name",
    #         "CreatedAt": "cr0b4_created_at",
    #         "UpdatedAt": "cr0b4_updated_at",
    #     },
    # },
}
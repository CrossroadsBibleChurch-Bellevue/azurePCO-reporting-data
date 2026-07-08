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
        "target_table": "dbo.PCO_GROUPS_OVERVIEW",
        "staging_table": "dbo.PCO_GROUPS_OVERVIEW_STAGING",
        "key_columns": ["HashId"],
        "required_source_keys": [
            "hash_id"
        ],
        "column_map": {
            "HashId": "hash_id",
            "GroupID": "group_id",
            "GroupName": "group_name",
            "MemberCount": "member_count",
            "EventCount": "event_count",
            "AvgEventAttendance": "avg_event_attendance_rate",
            "OverallAttendance": "overall_attendance_rate",
            "TotalAttended": "total_attended",
            "TotalAttendanceRecords": "total_attendance_records",
            "ArchivedAt": "archived_at",
        },
    },

    "group_snapshot": {
        "target_table": f"dbo.PCO_GROUPS_{snapshot}_SNAPSHOT",
        "staging_table": f"dbo.PCO_GROUPS_{snapshot}_SNAPSHOT_STAGING",
        "key_columns": ["HashId"],
        "required_source_keys": [
            "hash_id"
        ],
        "column_map": {
            "HashId": "hash_id",
            "GroupID": "group_id",
            "GroupName": "group_name",
            "MembershipID": "membership_id",
            "PersonID": "person_id",
            "MemberName": "member_name",
            "GroupRole": "role",
            "JoinedAt": "joined_at"
        },
    },

    "group_attendance": {
        "target_table": "dbo.PCO_GROUPS_placeholder",
        "staging_table": "dbo.PCO_GROUPS_placeholder_STAGING",
        "key_columns": ["HashId"],
        "required_source_keys": [
            "hash_id"
        ],
        "column_map": {
            "HashId": "hash_id",
            "GroupID": "group_id",
            "EventID": "event_id",
            "EventName": "event_name",
            "StartsAt": "starts_at",
            "PersonID": "person_id",
            "PersonName": "member_name",
            "MembershipRole": "membership_role",
            "Attended": "attended",
            "AttendanceRecordExists": "attendance_record_exists",
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
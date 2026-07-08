import os
from typing import Tuple
from dotenv import load_dotenv

load_dotenv()

DATAVERSE_ORG_URL = os.getenv("DATAVERSE_ORG_URL")

PCO_BASE_URL = os.getenv("PCO_BASE_URL")

PCO_PEOPLE_INCLUDE_PERSON = os.getenv("PCO_PEOPLE_INCLUDE_PERSON")

PCO_PEOPLE_INCLUDE_FIELD_DATA = os.getenv("PCO_PEOPLE_INCLUDE_FIELD_DATA")

group_limit_raw = os.getenv("GROUP_LIMIT")
group_limit = int(group_limit_raw) if group_limit_raw not in (None, "") else None
past_limit = os.getenv("PAST_LIMIT")
future_limit = os.getenv("FUTURE_LIMIT")
max_workers = os.getenv("GROUP_MAX_WORKERS")
include_archived = os.getenv("GROUPS_INCLUDE_ARCHIVED")
max_event_page_raw = os.getenv("GROUPS_MAX_EVENT_PAGES")
max_event_pages = int(max_event_page_raw) if max_event_page_raw not in (None, "") else None
mode = os.getenv("GROUPS_MODE")
skip_memberships = os.getenv("GROUPS_SKIP_MEMBERSHIPS")
skip_attendance = os.getenv("GROUPS_SKIP_ATTENDANCE")

# Get authentication from environmental variables for PCO
def get_auth_from_env() -> Tuple[str, str]:
    # Get app and secret ID, known as Client and Secret ID in PCO
    app_id = os.getenv("PCO_APP_ID")
    secret = os.getenv("PCO_SECRET")
    if not app_id or not secret:
        raise RuntimeError(
            "Missing env vars. Set:\n"
            "  PCO_APP_ID=your_app_id\n"
            "  PCO_SECRET=your_secret\n"
        )
    
    # Return auth variables
    return app_id, secret
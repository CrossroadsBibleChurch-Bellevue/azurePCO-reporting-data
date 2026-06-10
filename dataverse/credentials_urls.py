import os
from azure.identity import DefaultAzureCredential
from PowerPlatform.Dataverse.client import DataverseClient
from typing import Tuple

DATAVERSE_ORG_URL = os.getenv("DATAVERSE_ORG_URL")

PCO_BASE_URL = os.getenv("PCO_BASE_URL")

credential = DefaultAzureCredential()
client = DataverseClient(DATAVERSE_ORG_URL, credential)

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
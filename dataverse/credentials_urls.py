from azure.identity import DefaultAzureCredential
from PowerPlatform.Dataverse.client import DataverseClient
from utils.env_fetcher import DATAVERSE_ORG_URL


credential = DefaultAzureCredential()
client = DataverseClient(DATAVERSE_ORG_URL, credential)


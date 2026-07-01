from orchestrators.people_orchestrator_delta import main as sql
from orchestrators.people_orchestrator import main as chonkSQL
from dataverse.credentials_urls import client

#sql(client)

chonkSQL(client)
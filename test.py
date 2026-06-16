from extractors.people_extractor import main as main
from orchestrators.people_orchestrator import main as extractor_people
from dataverse.credentials_urls import client

#runner = main()

run = extractor_people(client)
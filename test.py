from extractors.people_extractor import main as main
from orchestrators.people_orchestrator import main as extractor_people
from orchestrators.people_orchestrator_updates import main as update_main
from extractors.people_incremental import main as people_extractor
from dataverse.credentials_urls import client

#runner = main()

#people_extractor()

update_main(client)

#run = extractor_people(client)
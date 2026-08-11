#from orchestrators.people_orchestrator_delta import main as sql
from orchestrators.people_orchestrator import main as chonkSQL
#from dataverse.credentials_urls import client
#from database.fetch_record import fetch_updated_at
#from orchestrators.groups_orchestrator_delta import main as groups
#from orchestrators.check_ins_orchestrator_full import main as checkin
#from orchestrators.check_ins_orchestrator_delta import main as delta
#from extractors.check_ins_extractor_full import extraction as checkin_extraction
#from extractors.groups_extractor_delta import extraction as table_fetch



#update = fetch_updated_at()

#print(update)
#sql()
#snapshot()
#groups()
chonkSQL()
#tables = table_fetch()
#tables = checkin_extraction()
#checkin()
#delta()


"""for table_name, rows in tables.items():
    print(f"\n{table_name}")

    if rows:
        print(rows[0])
    else:
        print("No rows")"""

#from orchestrators.people_orchestrator_delta import main as sql
#from orchestrators.people_orchestrator import main as chonkSQL
#from dataverse.credentials_urls import client
#from database.fetch_record import fetch_updated_at
from orchestrators.groups_orchestrator_delta import main as groups
#from extractors.groups_extractor_delta import extraction as table_fetch



#update = fetch_updated_at()

#print(update)
#sql()
#snapshot()
groups()
#chonkSQL()
#tables = table_fetch()


"""for table_name, rows in tables.items():
    print(f"\n{table_name}")

    if rows:
        print(rows[0])
    else:
        print("No rows")"""

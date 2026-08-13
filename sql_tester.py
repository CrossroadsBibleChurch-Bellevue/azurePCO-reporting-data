#from orchestrators.people_orchestrator_delta import main as sql
#from orchestrators.people_orchestrator import main as chonkSQL
#from database.fetch_record import fetch_updated_at
#from orchestrators.groups_orchestrator_delta import main as groups
#from orchestrators.check_ins_orchestrator_full import main as checkin
#from orchestrators.check_ins_orchestrator_delta import main as delta
from orchestrators.registrations_orchestrator_full import main as register_full
#from extractors.check_ins_extractor_full import extraction as checkin_extraction
#from extractors.groups_extractor_delta import extraction as table_fetch
#from extractors.registrations_extractor_full import extraction as registration_fetch

# So this is the tester file I would always use when trying to implement something for the first time when adding a new endpoint. I would first call just the extractor then using the for loop print out some sample rows from it to make sure it came out ok.
# Then after that, I would use the orchestrator to see if it upserted properly. Finally, I would run it with the function app locally before pushing to Azure.

#update = fetch_updated_at()

#print(update)
#sql()
#snapshot()
#groups()
#chonkSQL()
#tables = table_fetch()
#tables = checkin_extraction()
#tables = registration_fetch()
#checkin()
#delta()
register_full()

"""for table_name, rows in tables.items():
    print(f"\n{table_name}")

    if rows:
        print(rows[0])
    else:
        print("No rows")
"""
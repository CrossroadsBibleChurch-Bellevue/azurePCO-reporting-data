import azure.functions as func

from orchestrators.calendar_orchestrator import main as extractor_calendar
from orchestrators.people_orchestrator_full import main as deep_extractor_people
from orchestrators.people_orchestrator_delta import main as updates_extractor_people
from orchestrators.groups_orchestrator_full import main as groups_full_refresh
from orchestrators.groups_orchestrator_delta import main as groups_delta
from orchestrators.check_ins_orchestrator_delta import main as checkins_delta
from orchestrators.check_ins_orchestrator_full import main as checkins_full
from orchestrators.registrations_orchestrator_full import main as registrations_full
from orchestrators.groups_orchestrator_attendance import main as groups_attendance


# This is the start of the Azure Function. From here is where the actual code is called.
# Currently, there are two main functions/processes that get called and run, deep_data_extraction and regular_data_extraction
# Deep data extraction does full refreshes for everything, running once per month, fetching all the data again and then upserting to the database to ensure complete records and that nothing was missed
# Currently I am using three different functions to perform the deep data refresh, mainly because having all of them in the same call was too hard on the server it was on
# Regular data extraction does delta refreshes and runs once per day. It aims to get only the most recently updated data since the last data fetch
# When adding new modules for API endpoints that are not currently fetched, follow a similar structure to before, so that there is a full and delta refresh
# When the extractions occur is set by the app timer trigger schedule. It is in NCRON format, which can be read easily online.
# I use https://ncrontab.swimburger.net/, which shows the next times they will occur, and also can be used to find ideal schedules.
# For each endpoint the general structure used is the following. An orchestrator that these functions call, which then calls the extractor that actually gets the data, then pushes it to the uploader to then get upsert into the database.
# Also make sure if adding any environmental variables to add those in the Azure Function and if adding imports add those imports into requirements.txt

# 08/18/2026 v5

app = func.FunctionApp()


@app.timer_trigger(schedule="0 0 5 */1 * *", arg_name="myTimer", run_on_startup=False,
              use_monitor=False) 
def people_full_extraction(myTimer: func.TimerRequest) -> None:
    #extractor_calendar(client)
    deep_extractor_people()

@app.timer_trigger(schedule="0 0 2 */1 * *", arg_name="myTimer", run_on_startup=False,
              use_monitor=False) 
def groups_full_extraction(myTimer: func.TimerRequest) -> None:
    groups_full_refresh()

@app.timer_trigger(schedule="0 30 3 */1 * *", arg_name="myTimer", run_on_startup=True,
              use_monitor=False) 
def groups_attendance_extraction(myTimer: func.TimerRequest) -> None:
    groups_attendance()

@app.timer_trigger(schedule="0 0 6 */1 * *", arg_name="myTimer", run_on_startup=False,
              use_monitor=False) 
def checkins_full_extraction(myTimer: func.TimerRequest) -> None:
    checkins_full()

@app.timer_trigger(schedule="0 15 5 */1 * *", arg_name="myTimer", run_on_startup=False,
              use_monitor=False) 
def registrations_extraction(myTimer: func.TimerRequest) -> None:
    registrations_full()

@app.timer_trigger(schedule="0 30 0 */1 * *", arg_name="myTimer", run_on_startup=False,
              use_monitor=False) 
def delta_data_extraction(myTimer: func.TimerRequest) -> None:
    updates_extractor_people()
    groups_delta()
    checkins_delta()


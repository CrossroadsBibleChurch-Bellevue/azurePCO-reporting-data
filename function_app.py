import logging
import azure.functions as func

from dataverse.credentials_urls import client
from orchestrators.calendar_orchestrator import main as extractor_calendar
from orchestrators.people_orchestrator import main as deep_extractor_people
from orchestrators.people_orchestrator_delta import main as updates_extractor_people
from orchestrators.groups_orchestrator_snapshot import main as groups_snapshot
from orchestrators.groups_orchestrator_full import main as groups_full_refresh
from orchestrators.groups_orchestrator_delta import main as groups_delta

"""
To make a version that only fetches the most recent, since the last fetch, order the API pulls by -updated_at, so that it displays the most recent changes, then step through page by page until the updated at
is before the last fetch. This way, only the most recent, updated data is fetched, speeding up the process. A separate table or record would need to be created and kept so that the last full fetch and the last
incremental fetch would be recorded.
"""


app = func.FunctionApp()

@app.timer_trigger(schedule="0 0 0 1 * *", arg_name="myTimer", run_on_startup=False,
              use_monitor=False) 
def groups_monthly_snapshot(myTimer: func.TimerRequest) -> None:
    groups_snapshot()

@app.timer_trigger(schedule="0 0 0 3 * *", arg_name="myTimer", run_on_startup=True,
              use_monitor=False) 
def deep_data_extraction(myTimer: func.TimerRequest) -> None:
    #extractor_calendar(client)
    #deep_extractor_people(client)
    groups_full_refresh()

@app.timer_trigger(schedule="0 0 0 */1 * *", arg_name="myTimer", run_on_startup=False,
              use_monitor=False) 
def regular_data_extraction(myTimer: func.TimerRequest) -> None:
    #updates_extractor_people(client)
    groups_delta()


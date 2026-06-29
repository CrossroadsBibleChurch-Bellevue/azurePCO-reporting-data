import logging
import azure.functions as func

from dataverse.credentials_urls import client
from orchestrators.calendar_orchestrator import main as extractor_calendar
from orchestrators.people_orchestrator import main as extractor_people

"""
To make a version that only fetches the most recent, since the last fetch, order the API pulls by -updated_at, so that it displays the most recent changes, then step through page by page until the updated at
is before the last fetch. This way, only the most recent, updated data is fetched, speeding up the process. A separate table or record would need to be created and kept so that the last full fetch and the last
incremental fetch would be recorded.
"""


app = func.FunctionApp()

@app.timer_trigger(schedule="0 0 0 */1 * *", arg_name="myTimer", run_on_startup=False,
              use_monitor=False) 
def data_extraction(myTimer: func.TimerRequest) -> None:
    extractor_calendar(client)
    extractor_people(client)
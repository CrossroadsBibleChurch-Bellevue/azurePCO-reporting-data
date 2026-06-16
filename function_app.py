import logging
import azure.functions as func

from dataverse.credentials_urls import client
from orchestrators.calendar_orchestrator import main as extractor_calendar
from orchestrators.people_orchestrator import main as extractor_people

app = func.FunctionApp()

@app.timer_trigger(schedule="0 0 0 */1 * *", arg_name="myTimer", run_on_startup=False,
              use_monitor=False) 
def data_extraction(myTimer: func.TimerRequest) -> None:
    extractor_calendar(client)
    extractor_people(client)
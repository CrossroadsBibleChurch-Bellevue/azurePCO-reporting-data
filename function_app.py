import azure.functions as func

from orchestrators.calendar_orchestrator import main as extractor_calendar
from orchestrators.people_orchestrator import main as deep_extractor_people
from orchestrators.people_orchestrator_delta import main as updates_extractor_people
from orchestrators.groups_orchestrator_full import main as groups_full_refresh
from orchestrators.groups_orchestrator_delta import main as groups_delta
from orchestrators.check_ins_orchestrator_delta import main as checkins_delta
from orchestrators.check_ins_orchestrator_full import main as checkins_full



app = func.FunctionApp()


@app.timer_trigger(schedule="0 0 5 */1 * *", arg_name="myTimer", run_on_startup=False,
              use_monitor=False) 
def deep_data_extraction(myTimer: func.TimerRequest) -> None:
    #extractor_calendar(client)
    deep_extractor_people()
    groups_full_refresh()
    checkins_full()

@app.timer_trigger(schedule="0 0 0 */1 * *", arg_name="myTimer", run_on_startup=False,
              use_monitor=False) 
def regular_data_extraction(myTimer: func.TimerRequest) -> None:
    updates_extractor_people()
    groups_delta()
    checkins_delta()


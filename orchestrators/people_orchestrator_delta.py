import time

from extractors.people_extractor_delta import extraction_updates
from database.loader import uploader
from database.prepper import wake_up_server


# This is the orchestrator for the People endpoint, delta refresh. As you can see, it isn't much.
# Just runs the extractor and then gives that data to the uploader. Also makes sure the server is awake for when data needs to be pushed.


def main():
    t0 = time.perf_counter()
    wake_up_server()
    tables = extraction_updates()
    t1 = time.perf_counter()
    wake_up_server()
    uploader(tables, "people")
    t2 = time.perf_counter()
    print(f"Extract seconds: {t1 - t0:.2f}")
    print(f"Upload seconds:  {t2 - t1:.2f}")
    print(f"Total seconds taken: {t2 - t0:.2f}")

if __name__ == "__main__":
    print("No client configured. Please configure that and then run this again")
    main()
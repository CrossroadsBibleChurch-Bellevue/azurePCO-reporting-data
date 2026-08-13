import time

from extractors.people_extractor import extraction
from database.loader import uploader


# This is the orchestrator for the People endpoint, full refresh. As you can see, it isn't much.
# Just runs the extractor and then gives that data to the uploader. Also makes sure the server is awake for when data needs to be pushed.


def main():
    t0 = time.perf_counter()
    tables = extraction()
    t1 = time.perf_counter()

    try:
        uploader(tables, "people")
    finally:
        tables.clear()
        del tables
    t2 = time.perf_counter()
    print(f"Extract seconds: {t1 - t0:.2f}")
    print(f"Upload seconds:  {t2 - t1:.2f}")
    print(f"Total seconds taken: {t2 - t0:.2f}")

if __name__ == "__main__":
    main()
import time

from extractors.people_extractor_delta import extraction_updates
from database.loader import uploader
from database.prepper import wake_up_server

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
import time

from extractors.people_extractor import extraction
from database.loader import uploader

def main():
    t0 = time.perf_counter()
    tables = extraction()
    t1 = time.perf_counter()

    uploader(tables, "people")
    t2 = time.perf_counter()
    print(f"Extract seconds: {t1 - t0:.2f}")
    print(f"Upload seconds:  {t2 - t1:.2f}")
    print(f"Total seconds taken: {t2 - t0:.2f}")

if __name__ == "__main__":
    main()
import time
from extractors.check_ins_extractor_delta import extraction
from database.loader import uploader
from database.prepper import wake_up_server

def main():
    t0 = time.perf_counter()
    wake_up_server()
    tables = extraction()
    wake_up_server()
    t1 = time.perf_counter()
    #print(tables)

    uploader(tables, "check_ins")
    t2 = time.perf_counter()
    print(f"Extract seconds: {t1 - t0:.2f}")
    print(f"Upload seconds:  {t2 - t1:.2f}")
    print(f"Total seconds taken: {t2 - t0:.2f}")

if __name__ == "__main__":
    main()
import time
from extractors.groups_extractor_full import iter_extraction_chunks
from database.loader import uploader_from_stream
from database.prepper import wake_up_server


# This is the orchestrator for the Groups endpoint, full refresh. As you can see, it isn't much.
# Just runs the extractor and then gives that data to the uploader in batches. Also makes sure the server is awake for when data needs to be pushed.


def main():
    t0 = time.perf_counter()

    wake_up_server()

    try:
        uploader_from_stream(iter_extraction_chunks(batch_size=5000), "groups")
    finally:
        wake_up_server()

    t1 = time.perf_counter()
    print(f"Extract + Upload seconds: {t1 - t0:.2f}")
    print(f"Total seconds taken: {t1 - t0:.2f}")

if __name__ == "__main__":
    main()
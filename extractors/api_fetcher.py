from typing import Any, Tuple, Optional, Dict, List
import os
import time
import threading
import requests
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from dataverse.credentials_urls import PCO_BASE_URL

# This file contains various functions that are used by the PCO API fetchers and Dataverse uploaders. They are in this file so that this Azure Function is more modular and other API fetchers can in theory
# be implemented more easily. Also it makes the code more readable in general and not as long lol


# API rate limiter, using a token bucket (whatever that means lol)
class TokenBucket:
    """
    Simple (yeah... simple....) global rate limiter for concurrent threads.

    rate: tokens per second (RPS)
    burst: max tokens that can accumulate (burst capacity)
    """
    def __init__(self, rate: float, burst: int):
        self.rate = max(0.1, float(rate))
        self.capacity = max(1, int(burst))
        self.tokens = float(self.capacity)
        self.updated = time.monotonic()
        self.lock = threading.Lock()
        self.cv = threading.Condition(self.lock)

    def acquire(self, tokens: float = 1.0):
        tokens = float(tokens)
        if tokens <= 0:
            return

        with self.cv:
            while True:
                now = time.monotonic()
                elapsed = now - self.updated
                if elapsed > 0:
                    self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                    self.updated = now

                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return

                # sleep until enough tokens accrue
                needed = tokens - self.tokens
                sleep_s = needed / self.rate
                self.cv.wait(timeout=max(0.001, sleep_s))


# Global limiter configured by env
def _get_limiter() -> TokenBucket:
    rps = float(os.getenv("PCO_MAX_RPS", "8.0"))
    burst = int(os.getenv("PCO_BURST", "8"))
    return TokenBucket(rate=rps, burst=burst)


LIMITER = _get_limiter()

# Give each thread its own local storage, so variables don't get confused
_thread_local = threading.local()

# Function that returns a requests session for each thread worker
def get_session() -> requests.Session:
    # Get session if it exists
    s = getattr(_thread_local, "session", None)
    
    # If session doesn't exist for the thread create it
    if s is None:
        # Initialize request session
        s = requests.Session()

        # Set retry limits, what limits, etc.
        retry = Retry(
            total=5,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        # Get max workers and from there the pool of workers
        max_workers = int(os.getenv("PCO_MAX_WORKERS", "12"))
        pool = max(20, max_workers * 4)

        # Configure HTTP connection, pooling, retries, etc.
        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=pool,
            pool_maxsize=pool,
        )

        # Mount adapter onto the url for usage in the thread request session
        s.mount("https://", adapter)
        s.mount("http://", adapter)

        _thread_local.session = s
    return s


# Main function that sends API request and gets data from it as a response, rate-limiting does occur at times, handles it
def pco_get(path: str, auth: Tuple[str, str], params: Optional[Dict[str, str]] = None, session = None) -> Dict[str, Any]:
    # If special API call is needed (like to groups) this preps the URL
    if params and "url_override" in params:
        url = params.pop("url_override")
    else:
        url = f"{PCO_BASE_URL}{path}"
    
    # Get request session for the thread
    if session is None:
        s = get_session()
    else:
        s = session

    # We enforce a global RPS to avoid self-induced 429s when multithreading
    # Then we still do a small manual 429 loop in case the API is stricter than our limiter.

    # Attempt to hit the API, and back off if given a 429 error
    for attempt in range(1, 7):
        # Get rate limiter
        LIMITER.acquire(1.0)

        # Send off that request and get a response from the API
        resp = s.get(url, auth=auth, params=params, timeout=45)

        # If we get a 429 code, then get retry after limit from the response and sleep for that long
        if resp.status_code == 429:
            ra = resp.headers.get("Retry-After")
            if ra and ra.isdigit():
                sleep_s = float(ra)
            else:
                sleep_s = min(2 ** attempt, 30.0)
            time.sleep(sleep_s)
            continue
        
        # If neither ok response or 429, then raise error and apprioriate status code
        if not resp.ok:
            raise RuntimeError(f"GET {url} failed: {resp.status_code}\n{resp.text}")

        return resp.json()

    raise RuntimeError(f"GET {url} failed: too many 429s after retries")

# Function that gets all the data, stepping through page by page, could multi-thread to speed up process, which I may do eventually
def pco_get_all_pages(
    path: str,
    auth: Tuple[str, str],
    params: Optional[Dict[str, str]] = None,
    per_page: int = 100
) -> Dict[str, Any]:
    # Set params to empty if there is none for a successful request
    if params is None:
        params = {}
    
    # Get data entries per page (usually 100)
    per_page = max(1, min(int(per_page), 100))

    # Set variables
    all_data: List[Dict[str, Any]] = []
    included_map: Dict[Tuple[str, str], Dict[str, Any]] = {}

    # Offset counter
    offset = 0
    while True:
        # Set params to dictionary
        page_params = dict(params)
        # Set per_page and offset to a string
        page_params["per_page"] = str(per_page)
        page_params["offset"] = str(offset)

        # Fetch data, through pco_get
        payload = pco_get(path, auth, params=page_params)
        # Get page data, the main data from the API
        page_data = payload.get("data", []) or []
        # Seperate includes data from the payload
        page_included = payload.get("included", []) or []

        # 
        all_data.extend(page_data)

        # Step through the page includes
        for item in page_included:
            # Get type and ID from the includes
            t = item.get("type")
            i = item.get("id")
            # If type and ID exist, then add to the includes map, to make it easier later to step through and get data
            if t and i:
                included_map[(t, i)] = item

        # If the page data is less than per_page, it means we reached the end of the pages, so it is time to break the loop
        if len(page_data) < per_page:
            break

        # Add per page to the offset to get the next page
        offset += per_page

    # Return core data as well as the included data
    return {"data": all_data, "included": list(included_map.values())}
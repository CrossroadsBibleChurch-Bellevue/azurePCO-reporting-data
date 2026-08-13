from __future__ import annotations

import csv
import hashlib
import threading
import json
import logging
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from utils.time_functions import convert_output_datetimes_to_local_sql
from utils.hasher import stable_hash_id


BASE_URL = "https://api.planningcenteronline.com/registrations/v2"
API_VERSION = "2025-05-01"

OUTPUT_DIRECTORY = Path("registrations_output")
PER_PAGE = 100
REQUEST_TIMEOUT_SECONDS = 60
TERMINAL_PREVIEW_ROWS = 10
MAX_API_WORKERS = 8

SCRIPT_DIRECTORY = Path(__file__).resolve().parent

# Using an absolute path prevents the cache location from changing depending
# on the directory from which the script is executed.
API_CACHE_DIRECTORY = SCRIPT_DIRECTORY / ".pco_api_cache"

# Increment this when you make an intentional breaking change to the API
# request or cached response format.
API_CACHE_VERSION = 1

# True: load cached responses when available.
USE_API_CACHE = False

# True: always fetch from the API and replace existing cache files.
REFRESH_API_CACHE = False

# True: never call the API. Raise an error if a required cache entry is missing.
# Useful while changing parsing or table-building code.
CACHE_ONLY = False

TABLE_ORDER = [
    "signup",
    "signuptime",
    "registration",
    "registeringparty",
    "namedattendee",
    "attendeeselection",
    "signupcategory",
    "category",
    "selectiontype",
]


def relationship_id(
    resource: dict[str, Any],
    relationship_name: str,
) -> str | None:
    """
    Extract a to-one JSON:API relationship ID.
    """
    relationship = (
        resource.get("relationships", {})
        .get(relationship_name, {})
        .get("data")
    )

    if not isinstance(relationship, dict):
        return None

    relationship_value = relationship.get("id")
    return str(relationship_value) if relationship_value is not None else None


def relationship_ids(
    resource: dict[str, Any],
    relationship_name: str,
) -> list:
    """
    Extract one or more JSON:API relationship IDs.
    """
    relationship = (
        resource.get("relationships", {})
        .get(relationship_name, {})
        .get("data")
    )

    if relationship is None:
        return []

    if isinstance(relationship, dict):
        relationship_value = relationship.get("id")
        return (
            [str(relationship_value)]
            if relationship_value is not None
            else []
        )

    if isinstance(relationship, list):
        return [
            str(item["id"])
            for item in relationship
            if isinstance(item, dict) and item.get("id") is not None
        ]

    return []


def resource_type_key(resource_type: str | None) -> str:
    """
    Normalize resource type names such as SelectionType and selection_types
    so included resources can be found consistently.
    """
    if not resource_type:
        return ""

    return "".join(
        character.lower()
        for character in resource_type
        if character.isalnum()
    )


def get_resource_attributes(
    resource: dict[str, Any] | None,
) -> dict[str, Any]:
    if not resource:
        return {}

    attributes = resource.get("attributes")
    return attributes if isinstance(attributes, dict) else {}


def clean_csv_value(value: Any) -> Any:
    """
    Convert nested values into JSON strings for CSV output.
    """
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    return value

def parse_optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None



class PlanningCenterRegistrationsClient:
    def __init__(
        self,
        application_id: str,
        secret: str,
    ) -> None:
        self.application_id = application_id
        self.secret = secret

    def _create_session(self) -> requests.Session:
        """
        Create an independent session for one API collection fetch.

        Each concurrent worker receives its own requests.Session so sessions
        are never shared between threads.
        """
        session = requests.Session()
        session.auth = (
            self.application_id,
            self.secret,
        )
        session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": (
                    "PlanningCenter-Registrations-Tester/1.0"
                ),
                "X-PCO-API-Version": API_VERSION,
            }
        )

        retry_configuration = Retry(
            total=6,
            connect=6,
            read=6,
            status=6,
            backoff_factor=1.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )

        adapter = HTTPAdapter(
            max_retries=retry_configuration,
            pool_connections=MAX_API_WORKERS,
            pool_maxsize=MAX_API_WORKERS,
        )

        session.mount("https://", adapter)
        return session

    def close(self) -> None:
        """
        Sessions are created and closed within get_all_pages.
        This method is retained so main() does not need to change.
        """
        pass

    def _get_cache_path(
        self,
        endpoint: str,
        params: dict[str, Any] | None,
    ) -> Path:
        """
        Build a stable cache filename from the complete request identity.
        """
        normalized_params = dict(params or {})
        normalized_params.setdefault("per_page", PER_PAGE)

        normalized_endpoint = (
            endpoint
            if endpoint.startswith("http")
            else f"{BASE_URL}/{endpoint.lstrip('/')}"
        )

        cache_identity = {
            "cache_version": API_CACHE_VERSION,
            "base_url": BASE_URL,
            "api_version": API_VERSION,
            "endpoint": normalized_endpoint,
            "params": normalized_params,
        }

        serialized_identity = json.dumps(
            cache_identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

        cache_hash = hashlib.sha256(
            serialized_identity.encode("utf-8")
        ).hexdigest()

        return API_CACHE_DIRECTORY / f"{cache_hash}.json"


    def _load_cached_response(
        self,
        cache_path: Path,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
        """
        Load and validate one complete paginated API collection from disk.
        """
        if not cache_path.is_file():
            return None

        try:
            with cache_path.open("r", encoding="utf-8") as cache_file:
                cached_payload = json.load(cache_file)

            if not isinstance(cached_payload, dict):
                raise ValueError("Cached payload is not a JSON object.")

            if cached_payload.get("cache_version") != API_CACHE_VERSION:
                logging.info(
                    "Ignoring outdated cache entry: %s",
                    cache_path.name,
                )
                return None

            if cached_payload.get("api_version") != API_VERSION:
                logging.info(
                    "Ignoring cache entry from a different API version: %s",
                    cache_path.name,
                )
                return None

            cached_data = cached_payload.get("data")
            cached_included = cached_payload.get("included")

            if not isinstance(cached_data, list):
                raise ValueError("Cached data is not a list.")

            if not isinstance(cached_included, list):
                raise ValueError("Cached included data is not a list.")

            if not all(isinstance(item, dict) for item in cached_data):
                raise ValueError("Cached data contains non-object resources.")

            if not all(isinstance(item, dict) for item in cached_included):
                raise ValueError(
                    "Cached included data contains non-object resources."
                )


            return cached_data, cached_included

        except (OSError, json.JSONDecodeError, ValueError) as error:
            logging.warning(
                "Invalid API cache entry will be ignored: %s | %s",
                cache_path,
                error,
            )

            try:
                cache_path.unlink(missing_ok=True)
            except OSError:
                logging.warning(
                    "Could not remove invalid cache entry: %s",
                    cache_path,
                )

            return None


    def _save_cached_response(
        self,
        cache_path: Path,
        endpoint: str,
        params: dict[str, Any] | None,
        data: list[dict[str, Any]],
        included: list[dict[str, Any]],
    ) -> None:
        """
        Atomically save one complete paginated API collection.
        """
        API_CACHE_DIRECTORY.mkdir(
            parents=True,
            exist_ok=True,
        )

        normalized_params = dict(params or {})
        normalized_params.setdefault("per_page", PER_PAGE)

        cache_payload = {
            "cache_version": API_CACHE_VERSION,
            "base_url": BASE_URL,
            "api_version": API_VERSION,
            "endpoint": endpoint,
            "params": normalized_params,
            "cached_at_unix": time.time(),
            "data": data,
            "included": included,
        }

        temporary_path = cache_path.with_name(
            f".{cache_path.name}.{os.getpid()}."
            f"{threading.get_ident()}.tmp"
        )

        try:
            with temporary_path.open("w", encoding="utf-8") as cache_file:
                json.dump(
                    cache_payload,
                    cache_file,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )

                cache_file.flush()
                os.fsync(cache_file.fileno())

            os.replace(temporary_path, cache_path)


        finally:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                logging.warning(
                    "Could not remove temporary cache file: %s",
                    temporary_path,
                )


    def get_all_pages(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        not_found_is_empty: bool = False,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Load a complete API collection from cache when available.

        When CACHE_ONLY is enabled, an absent cache entry raises an error
        instead of making an API request.
        """
        cache_path = self._get_cache_path(
            endpoint=endpoint,
            params=params,
        )

        if USE_API_CACHE and not REFRESH_API_CACHE:
            cached_response = self._load_cached_response(cache_path)

            if cached_response is not None:
                return cached_response

        if CACHE_ONLY:
            raise RuntimeError(
                "Required API response is not cached and CACHE_ONLY is enabled.\n"
                f"Endpoint: {endpoint}\n"
                f"Parameters: {params or {}}\n"
                f"Expected cache file: {cache_path}"
            )


        data, included = self._fetch_all_pages_from_api(
            endpoint=endpoint,
            params=params,
            not_found_is_empty=not_found_is_empty,
        )

        if USE_API_CACHE:
            self._save_cached_response(
                cache_path=cache_path,
                endpoint=endpoint,
                params=params,
                data=data,
                included=included,
            )

        return data, included

    def _fetch_all_pages_from_api(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        not_found_is_empty: bool = False,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Fetch every page from a Planning Center JSON:API collection.

        Requests for separate collections can execute concurrently. Pagination
        within an individual collection remains sequential because each page
        supplies the URL for the next page.

        Returns:
            tuple:
                - Primary data resources
                - Included resources
        """
        url = (
            endpoint
            if endpoint.startswith("http")
            else f"{BASE_URL}/{endpoint.lstrip('/')}"
        )

        request_params = dict(params or {})
        request_params.setdefault("per_page", PER_PAGE)

        all_data: list[dict[str, Any]] = []
        all_included: list[dict[str, Any]] = []

        with self._create_session() as session:
            while url:
                response = session.get(
                    url,
                    params=request_params,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                if response.status_code == 404 and not_found_is_empty:
                    logging.debug(
                        "Optional Planning Center resource was not found: %s",
                        response.url,
                    )
                    return [], []

                if response.status_code == 429:
                    retry_after = response.headers.get(
                        "Retry-After",
                        "unknown",
                    )

                try:
                    response.raise_for_status()
                except requests.HTTPError as error:
                    response_preview = response.text[:2000]
                    raise RuntimeError(
                        "Planning Center request failed.\n"
                        f"URL: {response.url}\n"
                        f"Status: {response.status_code}\n"
                        f"Response: {response_preview}"
                    ) from error

                try:
                    payload = response.json()
                except requests.JSONDecodeError as error:
                    raise RuntimeError(
                        "Planning Center returned invalid JSON.\n"
                        f"URL: {response.url}\n"
                        f"Response: {response.text[:2000]}"
                    ) from error

                page_data = payload.get("data")
                page_included = payload.get("included", [])

                if page_data is None:
                    page_data = []
                elif isinstance(page_data, dict):
                    page_data = [page_data]
                elif not isinstance(page_data, list):
                    raise RuntimeError(
                        "Unexpected data format returned by "
                        f"{response.url}"
                    )

                if not isinstance(page_included, list):
                    page_included = []

                all_data.extend(page_data)
                all_included.extend(page_included)

                next_link = payload.get("links", {}).get("next")

                if isinstance(next_link, dict):
                    next_link = next_link.get("href")

                if next_link:
                    url = urljoin(response.url, next_link)
                    request_params = {}
                else:
                    url = ""

        return all_data, all_included

class RegistrationsTester:
    def __init__(
        self,
        client: PlanningCenterRegistrationsClient,
    ) -> None:
        self.client = client

        self.resources: dict[
            tuple[str, str],
            dict[str, Any],
        ] = {}

        self.tables: dict[str, list[dict[str, Any]]] = {
            table_name: []
            for table_name in TABLE_ORDER
        }

        self._seen_table_keys: dict[str, set[tuple[Any, ...]]] = defaultdict(set)

    def add_resources(
        self,
        resources: list[dict[str, Any]],
    ) -> None:
        for resource in resources:
            resource_id = resource.get("id")
            resource_type = resource_type_key(resource.get("type"))

            if resource_id is None or not resource_type:
                continue

            key = (resource_type, str(resource_id))
            existing_resource = self.resources.get(key)

            if existing_resource is None:
                self.resources[key] = resource
                continue

            existing_attributes = existing_resource.setdefault(
                "attributes",
                {},
            )
            existing_attributes.update(resource.get("attributes", {}))

            existing_relationships = existing_resource.setdefault(
                "relationships",
                {},
            )
            existing_relationships.update(resource.get("relationships", {}))

    def find_resource(
        self,
        resource_type: str,
        resource_id: str | None,
    ) -> dict[str, Any] | None:
        if resource_id is None:
            return None

        return self.resources.get(
            (
                resource_type_key(resource_type),
                str(resource_id),
            )
        )

    def append_unique(
        self,
        table_name: str,
        row: dict[str, Any],
        key_columns: tuple[str, ...],
    ) -> None:
        key = tuple(row.get(column) for column in key_columns)
        table_keys = self._seen_table_keys[table_name]

        if key in table_keys:
            return

        table_keys.add(key)
        self.tables[table_name].append(row)

    def fetch(self) -> dict[str, list[dict[str, Any]]]:
        logging.info("Fetching signups")

        signups, signup_included = self.client.get_all_pages(
            "signups",
            params={
                "include": (
                    "categories,"
                    "selection_types,"
                    "signup_times,"
                    "next_signup_time,"
                    "campuses"
                ),
                "fields[Signup]": (
                    "archived,"
                    "at_maximum_capacity,"
                    "close_at,"
                    "closed,"
                    "created_at,"
                    "description,"
                    "logo_url,"
                    "maximum_capacity,"
                    "name,"
                    "new_registration_url,"
                    "open,"
                    "open_at,"
                    "updated_at"
                ),
                "fields[SelectionType]": (
                    "at_maximum_capacity,"
                    "available_capacity,"
                    "created_at,"
                    "maximum_capacity,"
                    "name,"
                    "price_cents,"
                    "price_currency,"
                    "price_currency_symbol,"
                    "price_formatted,"
                    "publicly_available,"
                    "updated_at,"
                    "waitlist"
                ),
                "fields[SignupTime]": (
                    "all_day,"
                    "created_at,"
                    "ends_at,"
                    "starts_at,"
                    "updated_at"
                ),
            },
        )

        self.add_resources(signups)
        self.add_resources(signup_included)

        signup_count = len(signups)
        requests_per_signup = 5



        for signup_number, signup in enumerate(signups, start=1):
            signup_id = str(signup["id"])
            signup_name = get_resource_attributes(signup).get("name")


            self.build_signup_row(signup)
            self.build_signup_related_resource_rows(signup)

            endpoint_requests: dict[
                str,
                tuple[str, dict[str, Any] | None],
            ] = {
                "categories": (
                    f"signups/{signup_id}/categories",
                    None,
                ),
                "selection_types": (
                    f"signups/{signup_id}/selection_types",
                    {
                        "fields[SelectionType]": (
                            "at_maximum_capacity,"
                            "available_capacity,"
                            "created_at,"
                            "maximum_capacity,"
                            "name,"
                            "price_cents,"
                            "price_currency,"
                            "price_currency_symbol,"
                            "price_formatted,"
                            "publicly_available,"
                            "updated_at,"
                            "waitlist"
                        )
                    },
                ),
                "registrations": (
                    f"signups/{signup_id}/registrations",
                    {
                        "include": (
                            "created_by,registrant_contact"
                        ),
                    },
                ),
                "attendees": (
                    f"signups/{signup_id}/attendees",
                    {
                        "include": (
                            "person,"
                            "registration,"
                            "selection_type,"
                            "emergency_contact"
                        ),
                        "fields[Attendee]": (
                            "active,"
                            "canceled,"
                            "complete,"
                            "created_at,"
                            "name,"
                            "updated_at,"
                            "waitlisted,"
                            "waitlisted_at,"
                            "person,"
                            "registration,"
                            "selection_type,"
                            "emergency_contact"
                        ),
                        "fields[Person]": (
                            "first_name,"
                            "last_name,"
                            "name"
                        ),
                        "fields[SelectionType]": (
                            "at_maximum_capacity,"
                            "available_capacity,"
                            "created_at,"
                            "maximum_capacity,"
                            "name,"
                            "price_cents,"
                            "price_currency,"
                            "price_currency_symbol,"
                            "price_formatted,"
                            "publicly_available,"
                            "updated_at,"
                            "waitlist"
                        ),
                    },
                ),
                "signup_times": (
                    f"signups/{signup_id}/signup_times",
                    {
                        "fields[SignupTime]": (
                            "all_day,"
                            "created_at,"
                            "ends_at,"
                            "starts_at,"
                            "updated_at"
                        ),
                    },
                ),
            }

            endpoint_results: dict[
                str,
                tuple[
                    list[dict[str, Any]],
                    list[dict[str, Any]],
                ],
            ] = {}

            optional_not_found_requests = {
                "signup_times",
            }

            with ThreadPoolExecutor(
                max_workers=MAX_API_WORKERS,
                thread_name_prefix=f"pco-signup-{signup_id}",
            ) as executor:
                future_to_name = {
                    executor.submit(
                        self.client.get_all_pages,
                        endpoint,
                        params,
                        request_name in optional_not_found_requests,
                    ): request_name
                    for request_name, (
                        endpoint,
                        params,
                    ) in endpoint_requests.items()
                }

                for future in as_completed(future_to_name):
                    request_name = future_to_name[future]

                    try:
                        endpoint_results[request_name] = (
                            future.result()
                        )
                    except Exception as error:
                        raise RuntimeError(
                            "Failed fetching "
                            f"{request_name} for signup "
                            f"{signup_id} ({signup_name})"
                        ) from error


            categories, category_included = (
                endpoint_results["categories"]
            )
            selection_types, selection_type_included = (
                endpoint_results["selection_types"]
            )
            registrations, registration_included = (
                endpoint_results["registrations"]
            )
            attendees, attendee_included = (
                endpoint_results["attendees"]
            )

            signup_times, signup_time_included = (
                endpoint_results["signup_times"]
            )

            # Add every fetched resource before building rows. This ensures
            # resource lookups work regardless of which request completed first.
            self.add_resources(categories)
            self.add_resources(category_included)

            self.add_resources(selection_types)
            self.add_resources(selection_type_included)

            self.add_resources(registrations)
            self.add_resources(registration_included)

            self.add_resources(attendees)
            self.add_resources(attendee_included)

            self.add_resources(signup_times)
            self.add_resources(signup_time_included)

            for category in categories:
                self.build_category_row(category)
                self.build_signup_category_row(
                    signup_id=signup_id,
                    category_id=str(category["id"]),
                )

            for selection_type in selection_types:
                self.build_selection_type_row(
                    selection_type=selection_type,
                    signup_id=signup_id,
                )

            for registration in registrations:
                self.build_registration_row(
                    registration=registration,
                    signup_id=signup_id,
                )
                self.build_registering_party_row(
                    registration=registration,
                    signup_id=signup_id,
                )

            for attendee in attendees:
                self.build_named_attendee_row(
                    attendee=attendee,
                    signup_id=signup_id,
                )
                self.build_attendee_selection_row(
                    attendee=attendee,
                    signup_id=signup_id,
                )

                registration_id = relationship_id(
                    attendee,
                    "registration",
                )
                included_registration = self.find_resource(
                    "Registration",
                    registration_id,
                )

                if included_registration:
                    self.build_registration_row(
                        registration=included_registration,
                        signup_id=signup_id,
                    )
                    self.build_registering_party_row(
                        registration=included_registration,
                        signup_id=signup_id,
                    )

                selection_type_id = relationship_id(
                    attendee,
                    "selection_type",
                )
                included_selection_type = self.find_resource(
                    "SelectionType",
                    selection_type_id,
                )

                if included_selection_type:
                    self.build_selection_type_row(
                        selection_type=included_selection_type,
                        signup_id=signup_id,
                    )

            next_signup_time_id = relationship_id(
                signup,
                "next_signup_time",
            )

            for signup_time in signup_times:
                signup_time_id = str(signup_time["id"])

                self.build_signup_time_row(
                    signup_time=signup_time,
                    signup_id=signup_id,
                    is_next_signup_time=(
                        signup_time_id == next_signup_time_id
                    ),
                )

        self.sort_tables()
        return self.tables

    def build_signup_row(
        self,
        signup: dict[str, Any],
    ) -> None:
        signup_id = str(signup["id"])
        attributes = get_resource_attributes(signup)

        row = {
            "signup_id": int(signup_id),
            "name": attributes.get("name"),
            "archived": attributes.get("archived"),
            "open": attributes.get("open"),
            "closed": attributes.get("closed"),
            "at_maximum_capacity": attributes.get(
                "at_maximum_capacity"
            ),
            "maximum_capacity": attributes.get("maximum_capacity"),
            "open_at": attributes.get("open_at"),
            "close_at": attributes.get("close_at"),
            "created_at": attributes.get("created_at"),
            "updated_at": attributes.get("updated_at"),
        }

        self.append_unique(
            "signup",
            row,
            ("signup_id",),
        )

    def build_signup_time_row(
        self,
        signup_time: dict[str, Any],
        signup_id: str,
        is_next_signup_time: bool = False,
    ) -> None:
        signup_time_id = str(signup_time["id"])
        attributes = get_resource_attributes(signup_time)

        row = {
            "signup_time_id": int(signup_time_id),
            "signup_id": int(signup_id),
            "starts_at": attributes.get("starts_at"),
            "ends_at": attributes.get("ends_at"),
            "all_day": attributes.get("all_day"),
            "is_next_signup_time": is_next_signup_time,
            "created_at": attributes.get("created_at"),
            "updated_at": attributes.get("updated_at"),
        }

        existing_rows = self.tables["signuptime"]

        for existing_row in existing_rows:
            if (
                existing_row.get("signup_id") == signup_id
                and existing_row.get("signup_time_id") == signup_time_id
            ):
                if is_next_signup_time:
                    existing_row["is_next_signup_time"] = True
                return

        self.append_unique(
            "signuptime",
            row,
            ("signup_id", "signup_time_id"),
        )

    def build_signup_related_resource_rows(
        self,
        signup: dict[str, Any],
    ) -> None:
        signup_id = str(signup["id"])

        next_signup_time_id = relationship_id(
            signup,
            "next_signup_time",
        )

        signup_time_ids = relationship_ids(
            signup,
            "signup_times",
        )

        # Include next_signup_time even if it is unexpectedly absent from
        # the general signup_times relationship.
        all_signup_time_ids = list(
            dict.fromkeys(
                [
                    *signup_time_ids,
                    *(
                        [next_signup_time_id]
                        if next_signup_time_id is not None
                        else []
                    ),
                ]
            )
        )

        for signup_time_id in all_signup_time_ids:
            signup_time = self.find_resource(
                "SignupTime",
                signup_time_id,
            )

            if signup_time is None:
                continue

            self.build_signup_time_row(
                signup_time=signup_time,
                signup_id=signup_id,
                is_next_signup_time=(
                    signup_time_id == next_signup_time_id
                ),
            )

    def build_registration_row(
        self,
        registration: dict[str, Any],
        signup_id: str,
    ) -> None:
        registration_id = str(registration["id"])
        attributes = get_resource_attributes(registration)

        row = {
            "registration_id": int(registration_id),
            "signup_id": int(signup_id),
            "created_by_person_id": relationship_id(
                registration,
                "created_by",
            ),
            "registrant_contact_person_id": relationship_id(
                registration,
                "registrant_contact",
            ),
            "total_cost": attributes.get("total_cost"),
            "total_cost_cents": attributes.get("total_cost_cents"),
            "total_due": attributes.get("total_due"),
            "total_due_cents": attributes.get("total_due_cents"),
            "total_paid": attributes.get("total_paid"),
            "total_paid_cents": attributes.get("total_paid_cents"),
            "created_at": attributes.get("created_at"),
            "updated_at": attributes.get("updated_at"),
        }

        self.append_unique(
            "registration",
            row,
            ("registration_id",),
        )

    def build_registering_party_row(
        self,
        registration: dict[str, Any],
        signup_id: str,
    ) -> None:
        registration_id = str(registration["id"])

        registrant_contact_id = relationship_id(
            registration,
            "registrant_contact",
        )
        created_by_id = relationship_id(
            registration,
            "created_by",
        )

        registrant_contact = self.find_resource(
            "Person",
            registrant_contact_id,
        )
        created_by = self.find_resource(
            "Person",
            created_by_id,
        )

        registrant_attributes = get_resource_attributes(
            registrant_contact
        )
        created_by_attributes = get_resource_attributes(created_by)

        row = {
            "registration_id": int(registration_id),
            "signup_id": int(signup_id),
            "registrant_contact_person_id": registrant_contact_id,
            "created_by_person_id": created_by_id,
        }

        self.append_unique(
            "registeringparty",
            row,
            ("registration_id",),
        )

    def build_named_attendee_row(
        self,
        attendee: dict[str, Any],
        signup_id: str,
    ) -> None:
        attendee_id = str(attendee["id"])
        attributes = get_resource_attributes(attendee)

        person_id = relationship_id(
            attendee,
            "person",
        )

        person = self.find_resource(
            "Person",
            person_id,
        )
        person_attributes = get_resource_attributes(person)

        registration_id = relationship_id(
                attendee,
                "registration",
            )

        selection_type_id = relationship_id(
                attendee,
                "selection_type",
            )

        emergency_contact_id = relationship_id(
                attendee,
                "emergency_contact",
            )

        row = {
            "attendee_id": int(attendee_id),
            "person_id": (int(person_id) if person_id is not None else None),
            "signup_id": int(signup_id),
            "registration_id": int(registration_id) if registration_id is not None else None,
            "selection_type_id": int(selection_type_id) if selection_type_id is not None else None,
            "emergency_contact_id": int(emergency_contact_id) if emergency_contact_id is not None else None,
            "active": attributes.get("active"),
            "canceled": attributes.get("canceled"),
            "complete": attributes.get("complete"),
            "waitlisted": attributes.get("waitlisted"),
            "waitlisted_at": attributes.get("waitlisted_at"),
            "created_at": attributes.get("created_at"),
            "updated_at": attributes.get("updated_at"),
        }

        self.append_unique(
            "namedattendee",
            row,
            ("attendee_id",),
        )

    def build_attendee_selection_row(
        self,
        attendee: dict[str, Any],
        signup_id: str,
    ) -> None:
        attendee_id = str(attendee["id"])
        selection_type_id = relationship_id(
            attendee,
            "selection_type",
        )

        selection_type = self.find_resource(
            "SelectionType",
            selection_type_id,
        )
        selection_attributes = get_resource_attributes(
            selection_type
        )

        row = {
            "hash_id": stable_hash_id("attendee_selection", attendee_id, selection_type_id),
            "attendee_id": int(attendee_id) if attendee_id is not None else None,
            #"signup_id": signup_id,
            "selection_type_id": int(selection_type_id) if selection_type_id is not None else None,
            "attendee_active": get_resource_attributes(
                attendee
            ).get("active"),
            "attendee_canceled": get_resource_attributes(
                attendee
            ).get("canceled"),
            "attendee_waitlisted": get_resource_attributes(
                attendee
            ).get("waitlisted"),
        }

        self.append_unique(
            "attendeeselection",
            row,
            ("attendee_id", "selection_type_id"),
        )

    def build_signup_category_row(
        self,
        signup_id: str,
        category_id: str,
    ) -> None:
        row = {
            "hash_id": stable_hash_id("signup_category", signup_id, category_id),
            "signup_id": int(signup_id),
            "category_id": int(category_id),
        }

        self.append_unique(
            "signupcategory",
            row,
            ("signup_id", "category_id"),
        )

    def build_category_row(
        self,
        category: dict[str, Any],
    ) -> None:
        category_id = str(category["id"])
        attributes = get_resource_attributes(category)

        row = {
            "category_id": int(category_id),
            "name": attributes.get("name"),
            "created_at": attributes.get("created_at"),
            "updated_at": attributes.get("updated_at"),
        }

        self.append_unique(
            "category",
            row,
            ("category_id",),
        )

    def build_selection_type_row(
        self,
        selection_type: dict[str, Any],
        signup_id: str,
    ) -> None:
        selection_type_id = str(selection_type["id"])
        attributes = get_resource_attributes(selection_type)

        row = {
            "selection_type_id": int(selection_type_id),
            "signup_id": int(signup_id),
            "name": attributes.get("name"),
            "price_formatted": attributes.get("price_formatted"),
            "price_cents": attributes.get("price_cents"),
            "price_currency": attributes.get("price_currency"),
            "maximum_capacity": attributes.get("maximum_capacity"),
            "available_capacity": attributes.get(
                "available_capacity"
            ),
            "at_maximum_capacity": attributes.get(
                "at_maximum_capacity"
            ),
            "publicly_available": attributes.get(
                "publicly_available"
            ),
            "waitlist": attributes.get("waitlist"),
            "created_at": attributes.get("created_at"),
            "updated_at": attributes.get("updated_at"),
        }

        self.append_unique(
            "selectiontype",
            row,
            ("signup_id", "selection_type_id"),
        )

    def sort_tables(self) -> None:
        sort_columns = {
            "signup": ("signup_id",),
            "signuptime": (
                "signup_id",
                "starts_at",
                "signup_time_id",
            ),
            "registration": (
                "signup_id",
                "registration_id",
            ),
            "registeringparty": (
                "signup_id",
                "registration_id",
            ),
            "namedattendee": (
                "signup_id",
                "attendee_id",
            ),
            "attendeeselection": (
                "signup_id",
                "attendee_id",
            ),
            "signupcategory": (
                "signup_id",
                "category_id",
            ),
            "category": ("category_id",),
            "selectiontype": (
                "signup_id",
                "selection_type_id",
            ),
        }

        for table_name, columns in sort_columns.items():
            self.tables[table_name].sort(
                key=lambda row: tuple(
                    str(row.get(column) or "")
                    for column in columns
                )
            )



def load_credentials() -> tuple[str, str]:
    load_dotenv()

    application_id = os.getenv("PCO_APP_ID")
    secret = os.getenv("PCO_SECRET")

    missing_variables = [
        variable_name
        for variable_name, variable_value in (
            ("PCO_APP_ID", application_id),
            ("PCO_SECRET", secret),
        )
        if not variable_value
    ]

    if missing_variables:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing_variables)
        )

    return application_id, secret


def extraction() -> dict[str, list[dict[str, Any]]]:
    """
    Fetch and build all registration tables.

    Returns:
        A dictionary where:
            - Each key is a table name.
            - Each value is a list of row dictionaries.
    """
    application_id, secret = load_credentials()

    client = PlanningCenterRegistrationsClient(
        application_id=application_id,
        secret=secret,
    )

    try:
        tester = RegistrationsTester(client)
        tables = tester.fetch()
        convert_output_datetimes_to_local_sql(tables)
        return tables
    
    finally:
        client.close()



def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    start_time = time.perf_counter()

    try:
        tables = extraction()
        return 0

    except KeyboardInterrupt:
        logging.warning("Execution canceled by user.")
        return 130

    except Exception:
        logging.exception("Registrations tester failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
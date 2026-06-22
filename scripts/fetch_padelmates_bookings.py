import argparse
import json
import logging
import os
import sys
import time as time_module
from datetime import datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    HTTPError,
    RequestException,
    Timeout,
)


LOGIN_URL = "https://integrations.padelmates.io/login/"
ACTIVITY_URL = "https://integrations.padelmates.io/home/activity/"

APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = Path(os.getenv("PADEL_BOOKING_DATA_DIR", APP_DIR / "data"))
DEFAULT_CACHE_FILE = DEFAULT_DATA_DIR / "booking_cache.json"
DEFAULT_LOG_FILE = APP_DIR / "fetch_padel_bookings.log"
DEFAULT_TIMEZONE_NAME = "Europe/London"


@lru_cache(maxsize=8)
def get_timezone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        logging.error("Failed to load timezone: %s", timezone_name)
        logging.error("On Windows, install timezone data with: python -m pip install tzdata")
        raise


def setup_logging(log_level: str, log_file: Path) -> None:
    numeric_log_level = getattr(logging, log_level.upper(), logging.INFO)

    logger = logging.getLogger()
    logger.setLevel(numeric_log_level)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(funcName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_log_level)
    console_handler.setFormatter(formatter)

    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    logger.handlers.clear()
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    logging.info("Logging started.")
    logging.info("Console log level: %s", log_level.upper())
    logging.info("File log path: %s", log_file)


def mask_email(email: str) -> str:
    if not email or "@" not in email:
        return "***"

    name_part, domain_part = email.split("@", 1)
    masked_name = f"{name_part[:2]}***" if len(name_part) > 2 else f"{name_part[:1]}***"

    return f"{masked_name}@{domain_part}"


def mask_token(access_token: str) -> str:
    if not access_token or len(access_token) <= 10:
        return "***"

    return f"{access_token[:6]}...{access_token[-4:]}"


def extract_access_token(login_response_data: dict[str, Any]) -> str | None:
    possible_token_keys = [
        "access_token",
        "accessToken",
        "access_token_key",
        "token",
        "auth_token",
        "authToken",
        "jwt",
        "jwt_token",
    ]

    def search_dict(data: dict[str, Any], path: str = "root") -> str | None:
        for token_key in possible_token_keys:
            token_value = data.get(token_key)

            if isinstance(token_value, str) and token_value.strip():
                logging.debug("Access token found at path: %s.%s", path, token_key)
                return token_value

        for key, value in data.items():
            if isinstance(value, dict):
                nested_token = search_dict(value, path=f"{path}.{key}")

                if nested_token:
                    return nested_token

        return None

    return search_dict(login_response_data)


def log_login_response_shape(login_response_data: dict[str, Any]) -> None:
    logging.info("Login response top-level keys: %s", list(login_response_data.keys()))

    for key in ("user", "data"):
        value = login_response_data.get(key)

        if isinstance(value, dict):
            logging.info("Login response nested %s keys: %s", key, list(value.keys()))


def login(email: str, password: str, request_timeout_seconds: int) -> str:
    logging.info("Starting login request.")
    logging.debug("Login URL: %s", LOGIN_URL)
    logging.debug("Login email: %s", mask_email(email))

    headers = {
        "accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = {
        "email": email,
        "password": password,
    }

    request_start_time = time_module.perf_counter()

    try:
        response = requests.post(
            LOGIN_URL,
            headers=headers,
            json=payload,
            timeout=request_timeout_seconds,
        )
        elapsed_seconds = time_module.perf_counter() - request_start_time

        logging.info("Login response received in %.2f seconds.", elapsed_seconds)
        logging.info("Login HTTP status code: %s", response.status_code)
        response.raise_for_status()
    except Timeout:
        logging.exception("Login request timed out.")
        raise
    except RequestsConnectionError:
        logging.exception("Login connection error.")
        raise
    except HTTPError:
        logging.exception("Login HTTP error. Response text: %s", response.text)
        raise
    except RequestException:
        logging.exception("Login request failed.")
        raise

    try:
        login_response_data = response.json()
    except json.JSONDecodeError:
        logging.exception("Login response was not valid JSON. Response text: %s", response.text)
        raise

    log_login_response_shape(login_response_data)

    if login_response_data.get("success") is False:
        message = login_response_data.get("message")
        raise ValueError(f"Login failed. API message: {message}")

    access_token = extract_access_token(login_response_data)

    if not access_token:
        raise ValueError(
            "Login succeeded, but no access token was found. "
            "Check the log file for the response keys."
        )

    logging.info("Access token found: %s", mask_token(access_token))

    return access_token


def datetime_to_ms(datetime_value: datetime) -> int:
    return int(datetime_value.timestamp() * 1000)


def ms_to_datetime(milliseconds: int, timezone_name: str) -> datetime:
    local_timezone = get_timezone(timezone_name)
    return datetime.fromtimestamp(milliseconds / 1000, tz=local_timezone)


def get_booking_name(activity_record: dict[str, Any]) -> str:
    player_names = activity_record.get("player_names") or []

    if player_names:
        return ", ".join(str(name) for name in player_names)

    for key in ("coach_name", "title"):
        value = activity_record.get(key)

        if value:
            return str(value)

    return "Unknown"


def simplify_activity_record(activity_record: dict[str, Any], timezone_name: str) -> dict[str, Any]:
    activity_id = activity_record.get("activity_id") or activity_record.get("_id")

    if "start_datetime" not in activity_record:
        raise KeyError(f"Missing start_datetime for activity_id={activity_id}")

    if "end_datetime" not in activity_record:
        raise KeyError(f"Missing end_datetime for activity_id={activity_id}")

    start_datetime = ms_to_datetime(int(activity_record["start_datetime"]), timezone_name)
    end_datetime = ms_to_datetime(int(activity_record["end_datetime"]), timezone_name)
    booking_name = get_booking_name(activity_record)

    return {
        "booking_id": activity_id,
        "date": start_datetime.strftime("%Y-%m-%d"),
        "time": f"{start_datetime.strftime('%H:%M')} - {end_datetime.strftime('%H:%M')}",
        "name": booking_name,
        "name_and_id": f"{booking_name} | ID: {activity_id}",
        "court_names": activity_record.get("court_names", []),
        "activity_type": activity_record.get("activity_type"),
        "category": activity_record.get("category"),
        "raw_start_datetime": activity_record.get("start_datetime"),
        "raw_end_datetime": activity_record.get("end_datetime"),
    }


def fetch_bookings(
    access_token: str,
    club_id: str,
    start_ms: int,
    end_ms: int,
    request_timeout_seconds: int,
    timezone_name: str,
) -> list[dict[str, Any]]:
    logging.info("Starting bookings request.")
    logging.debug("Activity URL: %s", ACTIVITY_URL)
    logging.debug("Club ID: %s", club_id)
    logging.debug("Start milliseconds: %s", start_ms)
    logging.debug("End milliseconds: %s", end_ms)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    params = {
        "club_id": club_id,
        "start": start_ms,
        "end": end_ms,
    }
    request_start_time = time_module.perf_counter()

    try:
        response = requests.get(
            ACTIVITY_URL,
            headers=headers,
            params=params,
            timeout=request_timeout_seconds,
        )
        elapsed_seconds = time_module.perf_counter() - request_start_time

        logging.info("Bookings response received in %.2f seconds.", elapsed_seconds)
        logging.info("Bookings HTTP status code: %s", response.status_code)
        logging.debug("Final requested URL: %s", response.url)
        response.raise_for_status()
    except Timeout:
        logging.exception("Bookings request timed out.")
        raise
    except RequestsConnectionError:
        logging.exception("Bookings connection error.")
        raise
    except HTTPError:
        logging.exception("Bookings HTTP error. Response text: %s", response.text)
        raise
    except RequestException:
        logging.exception("Bookings request failed.")
        raise

    try:
        data = response.json()
    except json.JSONDecodeError:
        logging.exception("Bookings response was not valid JSON. Response text: %s", response.text)
        raise

    activity_records = data.get("activity_records", [])

    if not isinstance(activity_records, list):
        raise ValueError("Bookings response did not include an activity_records list.")

    bookings = [
        simplify_activity_record(activity_record, timezone_name)
        for activity_record in activity_records
        if isinstance(activity_record, dict)
    ]
    bookings.sort(key=lambda booking: booking["raw_start_datetime"] or 0)

    logging.info("Raw activity records received: %s", len(activity_records))
    logging.info("Simplified bookings created: %s", len(bookings))

    return bookings


def save_booking_cache(bookings: list[dict[str, Any]], output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with output_file.open("w", encoding="utf-8") as cache_file:
        json.dump(bookings, cache_file, indent=2, ensure_ascii=False)

    logging.info("Saved %s bookings to %s.", len(bookings), output_file)


def print_booking_list(bookings: list[dict[str, Any]]) -> None:
    booking_list = [
        f"{booking['date']} | {booking['time']} | {booking['name_and_id']}"
        for booking in bookings
    ]

    print("\nBookings list:")
    print(json.dumps(booking_list, indent=2, ensure_ascii=False))


def parse_start_date(start_date: str | None, timezone_name: str) -> datetime:
    local_timezone = get_timezone(timezone_name)

    if start_date:
        parsed_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    else:
        parsed_date = datetime.now(local_timezone).date()

    return datetime.combine(parsed_date, time.min, tzinfo=local_timezone)


def validate_arguments(args: argparse.Namespace) -> None:
    missing_fields = [
        option_name
        for option_name in ("email", "password", "club_id")
        if not getattr(args, option_name)
    ]

    if missing_fields:
        formatted_fields = ", ".join(missing_fields)
        raise ValueError(f"Missing required option(s): {formatted_fields}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch PadelMates bookings for a club and cache them as JSON."
    )
    parser.add_argument(
        "--club-id",
        default=os.getenv("PADELMATES_CLUB_ID"),
        help="PadelMates club ID. Can also be set using PADELMATES_CLUB_ID.",
    )
    parser.add_argument(
        "--email",
        default=os.getenv("PADELMATES_EMAIL"),
        help="PadelMates login email. Can also be set using PADELMATES_EMAIL.",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("PADELMATES_PASSWORD"),
        help="PadelMates login password. Can also be set using PADELMATES_PASSWORD.",
    )
    parser.add_argument(
        "--start-date",
        help="Start date in YYYY-MM-DD format. Defaults to today in the configured timezone.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to fetch. Defaults to 7.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_CACHE_FILE,
        help=f"JSON cache output path. Defaults to {DEFAULT_CACHE_FILE}.",
    )
    parser.add_argument(
        "--timezone",
        default=os.getenv("PADELMATES_TIMEZONE", DEFAULT_TIMEZONE_NAME),
        help=f"Timezone for date windows. Defaults to {DEFAULT_TIMEZONE_NAME}.",
    )
    parser.add_argument(
        "--request-timeout-seconds",
        type=int,
        default=30,
        help="Request timeout in seconds. Defaults to 30.",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=DEFAULT_LOG_FILE,
        help=f"Log file path. Defaults to {DEFAULT_LOG_FILE}.",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Console log level. Defaults to INFO.",
    )
    parser.add_argument(
        "--print-bookings",
        action="store_true",
        help="Print a compact booking list after saving the JSON cache.",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    setup_logging(args.log_level, args.log_file)

    try:
        validate_arguments(args)

        access_token = login(
            email=args.email,
            password=args.password,
            request_timeout_seconds=args.request_timeout_seconds,
        )

        start_datetime = parse_start_date(args.start_date, args.timezone)
        end_datetime = start_datetime + timedelta(days=args.days)
        start_ms = datetime_to_ms(start_datetime)
        end_ms = datetime_to_ms(end_datetime) - 1

        logging.info("Query window start: %s", start_datetime)
        logging.info("Query window end: %s", end_datetime)

        bookings = fetch_bookings(
            access_token=access_token,
            club_id=args.club_id,
            start_ms=start_ms,
            end_ms=end_ms,
            request_timeout_seconds=args.request_timeout_seconds,
            timezone_name=args.timezone,
        )

        save_booking_cache(bookings, args.output)

        if args.print_bookings:
            print_booking_list(bookings)

        print(f"\nSaved {len(bookings)} bookings to {args.output}")
        print(f"Logs saved to {args.log_file}")

    except Exception as error:
        logging.exception("Script failed with an error.")
        print("\nScript failed.")
        print(f"Error type: {type(error).__name__}")
        print(f"Error message: {error}")
        print(f"Check the log file for details: {args.log_file}")
        sys.exit(1)


if __name__ == "__main__":
    main()

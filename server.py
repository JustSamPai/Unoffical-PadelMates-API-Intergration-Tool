import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("PADEL_BOOKING_DATA_DIR", APP_DIR / "data"))
STATIC_DIR = APP_DIR / "static"

PADELMATES_CACHE_FILE = DATA_DIR / "booking_cache.json"
PLAYTOMIC_CACHE_FILE = DATA_DIR / "playtomic_cache.json"

DEFAULT_POLL_INTERVAL_SECONDS = 2
POLL_INTERVAL_SECONDS = float(
    os.getenv("PADEL_BOOKING_POLL_SECONDS", DEFAULT_POLL_INTERVAL_SECONDS)
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

app = FastAPI(
    title="Padel Booking Calendar",
    description="Compare local PadelMates and Playtomic booking cache files.",
    version="0.1.0",
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/bookings")
def get_bookings() -> dict[str, Any]:
    return build_calendar_payload()


@app.get("/api/health")
def get_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "padelmates_cache_exists": PADELMATES_CACHE_FILE.exists(),
        "playtomic_cache_exists": PLAYTOMIC_CACHE_FILE.exists(),
    }


@app.websocket("/ws/bookings")
async def bookings_websocket(websocket: WebSocket) -> None:
    await websocket.accept()

    logging.info("WebSocket client connected.")

    last_signature = None

    try:
        while True:
            current_signature = get_cache_signature()

            if current_signature != last_signature:
                payload = build_calendar_payload()
                await websocket.send_json(payload)
                last_signature = current_signature
                logging.info("Sent booking update to WebSocket client.")

            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    except WebSocketDisconnect:
        logging.info("WebSocket client disconnected.")


def get_cache_signature() -> tuple[Any, Any]:
    return (
        get_file_signature(PADELMATES_CACHE_FILE),
        get_file_signature(PLAYTOMIC_CACHE_FILE),
    )


def get_file_signature(file_path: Path) -> tuple[bool, float | None, int | None]:
    if not file_path.exists():
        return (False, None, None)

    stat = file_path.stat()
    return (True, stat.st_mtime, stat.st_size)


def load_json_list(file_path: Path) -> list[dict[str, Any]]:
    if not file_path.exists():
        return []

    try:
        with file_path.open("r", encoding="utf-8") as json_file:
            data = json.load(json_file)

    except json.JSONDecodeError:
        logging.exception("Could not decode JSON file: %s", file_path)
        return []

    if isinstance(data, dict):
        activity_records = data.get("activity_records")
        bookings = data.get("bookings")

        if isinstance(activity_records, list):
            return only_dict_records(activity_records, file_path)

        if isinstance(bookings, list):
            return only_dict_records(bookings, file_path)

    if isinstance(data, list):
        return only_dict_records(data, file_path)

    logging.warning("Unexpected JSON structure in file: %s", file_path)
    return []


def only_dict_records(records: list[Any], file_path: Path) -> list[dict[str, Any]]:
    valid_records = [record for record in records if isinstance(record, dict)]
    skipped_records = len(records) - len(valid_records)

    if skipped_records:
        logging.warning("Skipped %s non-object records in file: %s", skipped_records, file_path)

    return valid_records


def build_calendar_payload() -> dict[str, Any]:
    padelmates_raw = load_json_list(PADELMATES_CACHE_FILE)
    playtomic_raw = load_json_list(PLAYTOMIC_CACHE_FILE)

    padelmates_bookings = [
        normalize_booking(record, source="padelmates")
        for record in padelmates_raw
    ]

    playtomic_bookings = [
        normalize_booking(record, source="playtomic")
        for record in playtomic_raw
    ]

    playtomic_keys = {
        create_match_key(booking)
        for booking in playtomic_bookings
    }

    for booking in padelmates_bookings:
        booking["missing_in_playtomic"] = create_match_key(booking) not in playtomic_keys

    all_bookings = sorted(
        padelmates_bookings + playtomic_bookings,
        key=lambda booking: (
            booking.get("date", ""),
            booking.get("start_time", ""),
            booking.get("court_name", ""),
            booking.get("source", ""),
        ),
    )

    dates_with_mismatch = sorted({
        booking["date"]
        for booking in padelmates_bookings
        if booking.get("missing_in_playtomic")
    })

    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "padelmates_count": len(padelmates_bookings),
        "playtomic_count": len(playtomic_bookings),
        "dates_with_mismatch": dates_with_mismatch,
        "bookings": all_bookings,
    }


def normalize_booking(record: dict[str, Any], source: str) -> dict[str, Any]:
    booking_id = (
        record.get("booking_id")
        or record.get("activity_id")
        or record.get("_id")
        or record.get("id")
        or "unknown"
    )

    raw_start_datetime = record.get("raw_start_datetime") or record.get("start_datetime")
    raw_end_datetime = record.get("raw_end_datetime") or record.get("end_datetime")

    date = record.get("date")
    start_time = record.get("start_time")
    end_time = record.get("end_time")

    if raw_start_datetime and raw_end_datetime:
        start_dt = datetime_from_epoch_ms(raw_start_datetime)
        end_dt = datetime_from_epoch_ms(raw_end_datetime)

        if start_dt and end_dt:
            date = date or start_dt.strftime("%Y-%m-%d")
            start_time = start_time or start_dt.strftime("%H:%M")
            end_time = end_time or end_dt.strftime("%H:%M")

    if not start_time or not end_time:
        time_range = record.get("time", "")

        if " - " in time_range:
            start_time, end_time = time_range.split(" - ", 1)

    court_names = record.get("court_names") or []

    if isinstance(court_names, list) and court_names:
        court_name = str(court_names[0])
    else:
        court_name = (
            record.get("court_name")
            or record.get("court")
            or "Unknown court"
        )

    name = (
        record.get("name")
        or record.get("player_name")
        or first_from_list(record.get("player_names"))
        or record.get("coach_name")
        or record.get("title")
        or "Unknown"
    )

    activity_type = record.get("activity_type") or record.get("type") or ""
    category = record.get("category") or ""
    booking_type = record.get("booking_type") or ""
    title = record.get("title") or ""

    booking_kind = classify_booking_kind(
        activity_type=activity_type,
        category=category,
        booking_type=booking_type,
        title=title,
        source=source,
    )

    return {
        "booking_id": str(booking_id),
        "source": source,
        "date": date or "Unknown date",
        "start_time": start_time or "Unknown",
        "end_time": end_time or "Unknown",
        "time": f"{start_time or 'Unknown'} - {end_time or 'Unknown'}",
        "name": str(name),
        "court_name": str(court_name),
        "activity_type": str(activity_type),
        "category": str(category),
        "booking_type": str(booking_type),
        "title": str(title),
        "booking_kind": booking_kind,
        "missing_in_playtomic": False,
    }


def datetime_from_epoch_ms(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000)
    except (TypeError, ValueError, OSError, OverflowError):
        logging.warning("Invalid millisecond timestamp: %r", value)
        return None


def first_from_list(value: Any) -> str | None:
    if isinstance(value, list) and value:
        return str(value[0])

    return None


def classify_booking_kind(
    activity_type: str,
    category: str,
    booking_type: str,
    title: str,
    source: str,
) -> str:
    searchable_text = " ".join([
        activity_type,
        category,
        booking_type,
        title,
    ]).lower()

    if "block" in searchable_text or "blocked" in searchable_text:
        return "Open blocking"

    if (
        "training" in searchable_text
        or "lesson" in searchable_text
        or "course" in searchable_text
    ):
        return "Training / lesson"

    if (
        "book court" in searchable_text
        or "player booking" in searchable_text
        or "normal" in searchable_text
    ):
        return "Regular booking"

    if source == "playtomic":
        return "Playtomic booking"

    return "Other"


def create_match_key(booking: dict[str, Any]) -> str:
    return "|".join([
        normalize_key_value(booking.get("date")),
        normalize_key_value(booking.get("start_time")),
        normalize_key_value(booking.get("end_time")),
        normalize_key_value(booking.get("court_name")),
    ])


def normalize_key_value(value: Any) -> str:
    return str(value or "").strip().lower()

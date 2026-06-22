from datetime import datetime

from scripts import fetch_padelmates_bookings as fetcher


def test_mask_email_hides_local_part() -> None:
    assert fetcher.mask_email("sam@example.com") == "sa***@example.com"
    assert fetcher.mask_email("x@example.com") == "x***@example.com"
    assert fetcher.mask_email("not-an-email") == "***"


def test_extract_access_token_finds_nested_token() -> None:
    response_data = {
        "success": True,
        "user": {
            "profile": {"name": "Example"},
            "auth": {"access_token": "token-value"},
        },
    }

    assert fetcher.extract_access_token(response_data) == "token-value"


def test_simplify_activity_record_outputs_dashboard_cache_shape() -> None:
    start_datetime = datetime(2026, 6, 23, 9, 0).astimezone()
    end_datetime = datetime(2026, 6, 23, 10, 30).astimezone()
    activity_record = {
        "activity_id": "pm-123",
        "start_datetime": fetcher.datetime_to_ms(start_datetime),
        "end_datetime": fetcher.datetime_to_ms(end_datetime),
        "player_names": ["Alex Morgan"],
        "court_names": ["Court 1"],
        "activity_type": "Book court",
        "category": "Normal",
    }

    booking = fetcher.simplify_activity_record(activity_record, "Europe/London")

    assert booking["booking_id"] == "pm-123"
    assert booking["date"] == "2026-06-23"
    assert booking["time"] == "09:00 - 10:30"
    assert booking["name"] == "Alex Morgan"
    assert booking["court_names"] == ["Court 1"]

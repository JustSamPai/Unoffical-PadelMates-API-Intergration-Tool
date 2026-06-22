from pathlib import Path

import server


def test_normalize_booking_from_time_range() -> None:
    booking = server.normalize_booking(
        {
            "activity_id": "pm-1",
            "date": "2026-06-23",
            "time": "09:00 - 10:30",
            "court_names": ["Court 1"],
            "player_names": ["Alex Morgan"],
            "activity_type": "Book court",
            "booking_type": "Normal",
        },
        source="padelmates",
    )

    assert booking["booking_id"] == "pm-1"
    assert booking["date"] == "2026-06-23"
    assert booking["start_time"] == "09:00"
    assert booking["end_time"] == "10:30"
    assert booking["court_name"] == "Court 1"
    assert booking["name"] == "Alex Morgan"
    assert booking["booking_kind"] == "Regular booking"


def test_build_calendar_payload_flags_padelmates_missing_from_playtomic(
    tmp_path: Path,
    monkeypatch,
) -> None:
    padelmates_cache = tmp_path / "booking_cache.json"
    playtomic_cache = tmp_path / "playtomic_cache.json"

    padelmates_cache.write_text(
        """
        {
          "activity_records": [
            {
              "activity_id": "pm-1",
              "date": "2026-06-23",
              "time": "09:00 - 10:30",
              "court_name": "Court 1",
              "player_names": ["Alex Morgan"],
              "activity_type": "Book court"
            },
            {
              "activity_id": "pm-2",
              "date": "2026-06-23",
              "time": "12:00 - 13:00",
              "court_name": "Court 3",
              "player_names": ["Riley Chen"],
              "activity_type": "Training"
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    playtomic_cache.write_text(
        """
        {
          "bookings": [
            {
              "id": "pt-1",
              "date": "2026-06-23",
              "start_time": "09:00",
              "end_time": "10:30",
              "court": "Court 1",
              "player_name": "Alex Morgan"
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    monkeypatch.setattr(server, "PADELMATES_CACHE_FILE", padelmates_cache)
    monkeypatch.setattr(server, "PLAYTOMIC_CACHE_FILE", playtomic_cache)

    payload = server.build_calendar_payload()

    missing = [
        booking for booking in payload["bookings"]
        if booking["source"] == "padelmates" and booking["missing_in_playtomic"]
    ]

    assert payload["padelmates_count"] == 2
    assert payload["playtomic_count"] == 1
    assert payload["dates_with_mismatch"] == ["2026-06-23"]
    assert [booking["booking_id"] for booking in missing] == ["pm-2"]


def test_load_json_list_filters_non_object_records(tmp_path: Path) -> None:
    cache_file = tmp_path / "cache.json"
    cache_file.write_text('[{"id": "ok"}, "skip-me", 42]', encoding="utf-8")

    assert server.load_json_list(cache_file) == [{"id": "ok"}]


def test_invalid_epoch_timestamp_falls_back_to_unknown_time() -> None:
    booking = server.normalize_booking(
        {
            "id": "bad-time",
            "raw_start_datetime": "not-a-timestamp",
            "raw_end_datetime": "also-bad",
        },
        source="playtomic",
    )

    assert booking["date"] == "Unknown date"
    assert booking["start_time"] == "Unknown"
    assert booking["end_time"] == "Unknown"

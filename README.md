# Padel Booking Reconciliation Dashboard

An unofficial local dashboard for comparing PadelMates booking exports with
Playtomic booking exports. It treats PadelMates as the source of truth, flags
bookings that are missing from Playtomic, and streams updates to the browser as
local cache files change.

This project is not affiliated with, endorsed by, or supported by PadelMates or
Playtomic.

## What It Shows

- A FastAPI backend that normalizes booking data from two different export shapes.
- A live WebSocket workflow for keeping the browser in sync with local cache files.
- A lightweight browser UI for scanning court availability by date and booking source.
- Privacy-first repo hygiene: real booking exports stay local and are ignored by Git.
- Focused tests around the matching and normalization logic.

## Why I Built It

Booking systems can drift when a club uses multiple platforms. This tool makes
that drift visible by comparing PadelMates and Playtomic records on date, time,
and court. Mismatches are highlighted so staff can investigate them before they
turn into availability issues.

## Tech Stack

- Python 3.11+
- FastAPI
- Uvicorn
- Vanilla HTML, CSS, and JavaScript
- Pytest

## Features

- Live booking dashboard with WebSocket updates.
- REST endpoints for health checks and booking payloads.
- Matching by date, start time, end time, and court name.
- Booking classification for regular bookings, lessons, blocks, and Playtomic records.
- Sample JSON exports for demos and local development.
- `.gitignore` rules that keep private booking cache data out of source control.

## Quick Start

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the app with development tools:

```powershell
python -m pip install -e ".[dev]"
```

Add demo data:

```powershell
Copy-Item examples\padelmates_cache.sample.json data\booking_cache.json
Copy-Item examples\playtomic_cache.sample.json data\playtomic_cache.json
```

Run the server:

```powershell
uvicorn server:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

## Fetch PadelMates Data

The dashboard reads `data/booking_cache.json`. To create or refresh that file
from the PadelMates integration API, set your credentials locally:

```powershell
$env:PADELMATES_CLUB_ID = "your-club-id"
$env:PADELMATES_EMAIL = "you@example.com"
$env:PADELMATES_PASSWORD = "your-password"
```

Then run:

```powershell
python scripts\fetch_padelmates_bookings.py
```

Useful options:

```powershell
python scripts\fetch_padelmates_bookings.py --start-date 2026-06-22 --days 14
python scripts\fetch_padelmates_bookings.py --output data\booking_cache.json --print-bookings
```

The script writes the dashboard cache format and masks credentials in logs.
Generated `.log` files and `data/*.json` files are ignored by Git.

## API Endpoints

| Endpoint | Description |
| --- | --- |
| `GET /` | Serves the dashboard UI. |
| `GET /api/health` | Reports service status and whether cache files exist. |
| `GET /api/bookings` | Returns the normalized calendar payload. |
| `WS /ws/bookings` | Streams booking payload updates when cache files change. |

## Data Files

By default, the app reads local cache files from:

```text
data/booking_cache.json
data/playtomic_cache.json
```

The loader accepts either a list of booking objects or an object containing one
of these fields:

- `activity_records`
- `bookings`

Real exports may contain names, IDs, schedules, and operational details. Files
matching `data/*.json` are ignored by Git. Use the safe sample files in
`examples/` for demos, issues, and screenshots.

## Configuration

Override the data directory:

```powershell
$env:PADEL_BOOKING_DATA_DIR = "C:\path\to\cache-folder"
```

Change the WebSocket polling interval:

```powershell
$env:PADEL_BOOKING_POLL_SECONDS = "5"
```

## Development

Run tests:

```powershell
python -m pytest
```

Run linting:

```powershell
python -m ruff check .
```

## Project Structure

```text
.
|-- server.py                 # FastAPI app, cache loading, normalization, matching
|-- scripts/                  # Local data-fetching scripts
|-- static/                   # Browser UI
|-- examples/                 # Safe sample cache files
|-- data/                     # Local runtime cache files, ignored except .gitkeep
|-- tests/                    # Backend tests
|-- pyproject.toml            # Runtime and dev dependencies
`-- LICENSE
```

## Roadmap

- Add a screenshot or short demo GIF for the GitHub project page.
- Support configurable matching rules for clubs with different court naming schemes.
- Add import adapters for additional booking export formats.
- Add a CI workflow for tests and linting.

## License

MIT. See [LICENSE](LICENSE).

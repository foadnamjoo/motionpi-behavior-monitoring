# MotionPI Active Participants Report

MongoDB-backed report for active participants: table and charts by data source (location, ENMO, surveys, logs, batteries) with configurable time window and timezone.

## Features

- **CLI**: Run queries from the terminal (`python mongodb_query.py`).
- **Web report**: HTML app + Flask server — choose time window, run report, view table and chart, download CSV and PNG.
- **Standalone HTML**: Share the HTML file; users enter the report server URL and run reports without installing Python.

## Setup

1. **Clone and enter the repo**
   ```bash
   git clone https://github.com/YOUR_USERNAME/motionpi-report.git
   cd motionpi-report
   ```

2. **Create a virtual environment and install dependencies**
   ```bash
   python3 -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configure MongoDB**
   - Copy `.env.example` to `.env`.
   - Set `MONGODB_URI` to your connection string (same as in MongoDB Compass).

## Usage

### Command-line report

```bash
source venv/bin/activate
python mongodb_query.py
```

Uses the default weekly report (last 7 days, America/Denver). Edit `QUERIES` in `mongodb_query.py` to change.

### Web report (for you or your supervisor)

1. **Start the server** (on a machine that can reach MongoDB):
   ```bash
   source venv/bin/activate
   python report_server.py
   ```
   Server runs at **http://127.0.0.1:5050** (or the host’s IP if accessed from another device).

2. **Open the report**
   - From the same machine: open **http://127.0.0.1:5050/** in a browser.
   - From another computer: open the **report_app.html** file, enter the server URL (e.g. `http://server-ip:5050`), then run the report.

No Python is required on the supervisor’s machine when using the standalone HTML + server URL.

## Project structure

| File / folder      | Purpose |
|--------------------|--------|
| `mongodb_query.py` | Query definitions, time filters, report logic, CLI and plot generation |
| `report_server.py` | Flask API for the web report |
| `report_app.html`  | Single-page report UI (table, chart, CSV/PNG download) |
| `.env`             | MongoDB URI (create from `.env.example`, do not commit) |
| `requirements.txt` | Python dependencies |

## Time windows and collections

- **Time window**: Last 24 hours or last 7 days (MST/SLC by default).
- **Collections**: `userlocations`, `userenmos`, `surveys`, `userlogs`, `userbatteries` (per-collection timestamp units: ms vs seconds as in `COLLECTION_TIMESTAMP_UNITS`).

## License

Use as needed for the MotionPI project.

# MotionPI Active Participants Report

MongoDB-backed report for active participants: table and charts by data source (location, ENMO, surveys, logs, batteries) with configurable time window and timezone.

## Features

- **CLI**: Run queries from the terminal (`python mongodb_query.py`).
- **Web report**: HTML app + Flask server — choose time window, run report, view table and chart, download CSV and PNG.
- **Standalone HTML**: Share the HTML file; users enter the report server URL and run reports without installing Python.

## Setup

1. **Clone and enter the repo**
   ```bash
   git clone https://github.com/foadnamjoo/motionpi-surveillance.git
   cd motionpi-surveillance
   ```

2. **Create a virtual environment and install dependencies**
   ```bash
   python3 -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configure MongoDB**
   - Copy `.env.example` to `.env`.
   - Set `MONGODB_URI` to your connection string (from MongoDB Compass or your provider). **Do not commit `.env`.**

## Usage

### Command-line report

```bash
source venv/bin/activate
python mongodb_query.py
```

Uses the default weekly report (last 7 days, America/Denver). Edit `QUERIES` in `mongodb_query.py` to change.

### Web report

1. **Start the server** (on a machine that can reach MongoDB):
   ```bash
   source venv/bin/activate
   python report_server.py
   ```
   By default the server binds to **127.0.0.1:5050** (local only). Open **http://127.0.0.1:5050/** in a browser.

2. **Optional deployment settings** (environment variables):
   - `REPORT_HOST` — e.g. `0.0.0.0` to listen on all interfaces (only if needed and network is trusted).
   - `REPORT_PORT` — default `5050`.
   - `REPORT_DEBUG` — set to `1` or `true` only for local development; never in production.
   - `CORS_ORIGIN` — if the HTML is opened from another origin (e.g. file or different domain), set to that origin or `*`. Leave unset for same-origin only (recommended when the page is served from this server).
   - `REPORT_API_KEY` — if set, the API requires the `X-API-Key` header (or `api_key` query param) to match. Use in production to protect the report endpoint.

3. **Standalone HTML**: Open `report_app.html` elsewhere, enter the report server URL, and run the report. The server must have `CORS_ORIGIN` set (e.g. `*` or the page origin) for cross-origin requests to work; prefer also setting `REPORT_API_KEY`.

## Security

- **Never commit** `.env`, credentials, tokens, or private URLs. Use `.env.example` only as a template.
- **Server defaults** are safe: `debug=False`, `host=127.0.0.1`. Override with env vars only when needed.
- **CORS**: Disabled by default. Set `CORS_ORIGIN` only when you need cross-origin access (e.g. standalone HTML); use a specific origin instead of `*` when possible.
- **API key**: Set `REPORT_API_KEY` in production and send it in the `X-API-Key` header (or `api_key` query) from the client if you expose the server beyond localhost.

## Project structure

| File / folder      | Purpose |
|--------------------|--------|
| `mongodb_query.py` | Query definitions, time filters, report logic, CLI and plot generation |
| `report_server.py` | Flask API for the web report |
| `report_app.html`  | Single-page report UI (table, chart, CSV/PNG download) |
| `.env`             | MongoDB URI (create from `.env.example`, do not commit) |
| `requirements.txt` | Python dependencies |

## Time windows and collections

- **Time window**: Last 24 hours or last 7 days (America/Denver by default).
- **Collections**: `userlocations`, `userenmos`, `surveys`, `userlogs`, `userbatteries` (per-collection timestamp units: ms vs seconds as in `COLLECTION_TIMESTAMP_UNITS`).

## License

Use as needed for the MotionPI project.

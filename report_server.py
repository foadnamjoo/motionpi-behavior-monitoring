#!/usr/bin/env python3
"""
Web server for the active-participants report. Run: python report_server.py
Open the HTML page, choose time window, click Run report; view table and plot, download CSV and PNG.

Security: Uses safe defaults (no debug, bind 127.0.0.1). CORS and optional API key
are configured via environment variables. See README.
"""

import base64
import os
import traceback
from datetime import datetime

from dotenv import load_dotenv

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

load_dotenv()

try:
    from flask import Flask, send_file, request, jsonify
except ImportError:
    print("Install Flask: pip install flask")
    raise

from mongodb_query import (
    get_client,
    _get_filter_for_collection,
    REPORT_COLLECTIONS,
    REPORT_COL_LABELS,
    COLLECTION_TIMESTAMP_UNITS,
    _plot_daily_report_to_bytes,
)

app = Flask(__name__)

# Safe defaults: no debug, localhost only. Override with env for your deployment.
DEBUG = os.environ.get("REPORT_DEBUG", "").lower() in ("1", "true", "yes")
HOST = os.environ.get("REPORT_HOST", "127.0.0.1")
PORT = int(os.environ.get("REPORT_PORT", "5050"))
CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "").strip()  # If set, allow this origin (e.g. * or https://app.example.com)
REPORT_API_KEY = os.environ.get("REPORT_API_KEY", "").strip()  # If set, require X-API-Key header


def _check_api_key():
    if not REPORT_API_KEY:
        return True
    key = request.headers.get("X-API-Key") or request.args.get("api_key")
    return key == REPORT_API_KEY


@app.after_request
def add_cors(resp):
    origin = CORS_ORIGIN
    if not origin and HOST in ("127.0.0.1", "localhost", "::1"):
        # Allow file:// and other origins when running locally so the app works when opened as a file
        origin = "*"
    if origin:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key"
    return resp


def _parse_time_to_epoch(value, tz_name="America/Denver"):
    """Convert start_time/end_time to Unix seconds. Accepts Unix number or ISO-like string (local in tz)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            tz = ZoneInfo(tz_name)
            dt = dt.replace(tzinfo=tz)
        return dt.timestamp()
    except Exception:
        return None


def run_report(
    last_days=None,
    last_hours=24,
    timezone_name="America/Denver",
    collections=None,
    start_time=None,
    end_time=None,
):
    """Run the report; return (participant_ids, table, time_label, run_timestamp)."""
    coll_list = list(collections) if collections else list(REPORT_COLLECTIONS)
    coll_list = [c for c in coll_list if c in REPORT_COLLECTIONS]
    if not coll_list:
        coll_list = list(REPORT_COLLECTIONS)

    q = {
        "db": "test",
        "collections": coll_list,
        "key": "participantID",
        "filter": {},
        "timezone": timezone_name,
        "collection_timestamp_units": COLLECTION_TIMESTAMP_UNITS,
    }

    start_ts = _parse_time_to_epoch(start_time, timezone_name)
    end_ts = _parse_time_to_epoch(end_time, timezone_name)
    if start_ts is not None and end_ts is not None:
        q["start_ts"] = start_ts
        q["end_ts"] = end_ts
        tz = ZoneInfo(timezone_name)
        time_label = (
            datetime.fromtimestamp(start_ts, tz=tz).strftime("%Y-%m-%d")
            + "_to_"
            + datetime.fromtimestamp(end_ts, tz=tz).strftime("%Y-%m-%d")
        )
        display_label = (
            datetime.fromtimestamp(start_ts, tz=tz).strftime("%Y-%m-%d %H:%M")
            + " to "
            + datetime.fromtimestamp(end_ts, tz=tz).strftime("%Y-%m-%d %H:%M")
        )
    elif last_days is not None:
        q["last_days"] = last_days
        time_label = f"last_{last_days}days"
        display_label = f"last {last_days} days"
    else:
        q["last_hours"] = last_hours or 24
        time_label = "last_24h"
        display_label = "last 24 hours"

    client = get_client()
    db = client[q["db"]]
    key = q["key"]
    collections = q["collections"]
    # Step 1: Active participants
    active_ids = set()
    for coll_name in collections:
        coll = db[coll_name]
        coll_filter = _get_filter_for_collection(q, coll_name)
        active_ids.update(coll.distinct(key, coll_filter))
    participant_ids = sorted(active_ids)
    # Step 2: Counts per participant per collection
    table = {}
    for coll_name in collections:
        coll = db[coll_name]
        coll_filter = _get_filter_for_collection(q, coll_name)
        for doc in coll.aggregate([
            {"$match": coll_filter},
            {"$group": {"_id": f"${key}", "count": {"$sum": 1}}},
        ]):
            pid = doc["_id"]
            if pid not in table:
                table[pid] = {}
            table[pid][coll_name] = doc["count"]
    run_ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    return participant_ids, table, display_label, time_label, run_ts, coll_list


def table_to_rows(participant_ids, table, collections):
    """Return [header_row, ...data_rows] for CSV and HTML table."""
    headers = ["participantID"] + [REPORT_COL_LABELS.get(c, c) for c in collections]
    rows = [headers]
    for pid in participant_ids:
        row = table.get(pid, {})
        rows.append([str(pid)] + [row.get(c, 0) for c in collections])
    return rows


_ROOT = os.path.dirname(os.path.abspath(__file__))


@app.route("/")
def index():
    return send_file(os.path.join(_ROOT, "report_app.html"))


@app.route("/api/report", methods=["OPTIONS"])
def report_options():
    return "", 204


@app.route("/api/report", methods=["POST"])
def api_report():
    if not _check_api_key():
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json() or {}
    last_days = data.get("last_days")
    last_hours = data.get("last_hours", 24)
    tz = data.get("timezone", "America/Denver")
    collections = data.get("collections")
    start_time = data.get("start_time")
    end_time = data.get("end_time")
    if last_days is not None and start_time is None and end_time is None:
        last_hours = None
    try:
        participant_ids, table, display_label, time_label, run_ts, coll_list = run_report(
            last_days=last_days,
            last_hours=last_hours,
            timezone_name=tz,
            collections=collections,
            start_time=start_time,
            end_time=end_time,
        )
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    rows = table_to_rows(participant_ids, table, coll_list)
    date_part = datetime.now().strftime("%Y-%m-%d")
    safe_label = time_label.replace(" ", "")
    tz_suffix = tz.split("/")[-1] if "/" in tz else tz
    csv_filename = f"report_{date_part}_{run_ts}_{safe_label}_{tz_suffix}.csv"
    plot_filename = f"report_{date_part}_{run_ts}_{safe_label}_{tz_suffix}.png"
    try:
        plot_bytes, _ = _plot_daily_report_to_bytes(
            participant_ids, coll_list, table,
            col_labels=REPORT_COL_LABELS,
            time_label=display_label,
            out_basename="report",
        )
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Plot failed: {e}"}), 500
    plot_b64 = base64.b64encode(plot_bytes).decode("utf-8") if plot_bytes else None
    return jsonify({
        "table": rows,
        "participant_ids": participant_ids,
        "time_label": display_label,
        "run_timestamp": run_ts,
        "csv_filename": csv_filename,
        "plot_filename": plot_filename,
        "plot_base64": plot_b64,
    })


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=DEBUG)

#!/usr/bin/env python3
"""
Web server for the active-participants report. Run: python report_server.py
Open the HTML page, choose time window, click Run report; view table and plot, download CSV and PNG.
"""

import base64
import os
from datetime import datetime

from dotenv import load_dotenv

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


@app.after_request
def add_cors(resp):
    """Allow standalone HTML (file:// or another origin) to call the API."""
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


def run_report(last_days=None, last_hours=24, timezone_name="America/Denver"):
    """Run the report; return (participant_ids, table, time_label, run_timestamp)."""
    q = {
        "db": "test",
        "collections": REPORT_COLLECTIONS,
        "key": "participantID",
        "filter": {},
        "timezone": timezone_name,
        "collection_timestamp_units": COLLECTION_TIMESTAMP_UNITS,
    }
    if last_days is not None:
        q["last_days"] = last_days
        time_label = f"last_{last_days}days"
    else:
        q["last_hours"] = last_hours or 24
        time_label = "last_24h"
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
    display_label = f"last {last_days} days" if last_days else "last 24 hours"
    run_ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    return participant_ids, table, display_label, time_label, run_ts


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
    data = request.get_json() or {}
    last_days = data.get("last_days")
    last_hours = data.get("last_hours", 24)
    tz = data.get("timezone", "America/Denver")
    if last_days is not None:
        last_hours = None
    try:
        participant_ids, table, display_label, time_label, run_ts = run_report(
            last_days=last_days, last_hours=last_hours, timezone_name=tz
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    collections = REPORT_COLLECTIONS
    rows = table_to_rows(participant_ids, table, collections)
    # Filenames: report_2026-02-10_14-30_last7days_MST.csv / .png
    date_part = datetime.now().strftime("%Y-%m-%d")
    safe_label = time_label.replace(" ", "")
    csv_filename = f"report_{date_part}_{run_ts}_{safe_label}_{tz.split('/')[-1]}.csv"
    plot_filename = f"report_{date_part}_{run_ts}_{safe_label}_{tz.split('/')[-1]}.png"
    plot_bytes, _ = _plot_daily_report_to_bytes(
        participant_ids, collections, table,
        col_labels=REPORT_COL_LABELS,
        time_label=display_label,
        out_basename="report",
    )
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
    app.run(host="0.0.0.0", port=5050, debug=True)

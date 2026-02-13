#!/usr/bin/env python3
"""
MongoDB query runner — run from Cursor (Terminal or Run task).
Set MONGODB_URI in .env or environment. Edit QUERIES below or pass a JSON file.
"""

import os
import sys
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

try:
    from pymongo import MongoClient
except ImportError:
    print("Install dependencies: pip install pymongo python-dotenv")
    sys.exit(1)

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    _HAS_MATPLOTLIB = True
except ImportError:
    _HAS_MATPLOTLIB = False

# --- Configure: add your default queries here ---
# Per-collection timestamp unit: surveys/userbatteries = ms; userenmos/userlocations/userlogs = seconds
COLLECTION_TIMESTAMP_UNITS = {
    "surveys": "milliseconds",
    "userbatteries": "milliseconds",
    "userenmos": "seconds",
    "userlocations": "seconds",
    "userlogs": "seconds",
}
# Report column order and display names: location / ENMO / surveys / logs / batteries
REPORT_COLLECTIONS = ["userlocations", "userenmos", "surveys", "userlogs", "userbatteries"]
REPORT_COL_LABELS = {"userlocations": "location", "userenmos": "ENMO", "surveys": "surveys", "userlogs": "logs", "userbatteries": "batteries"}

QUERIES = [
    {
        "name": "weekly_report_7d",
        "db": "test",
        "collections": REPORT_COLLECTIONS,
        "action": "daily_report",
        "key": "participantID",
        "filter": {},
        "last_days": 7,
        "timezone": "America/Denver",
        "collection_timestamp_units": COLLECTION_TIMESTAMP_UNITS,
    },
]


def get_client():
    uri = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
    return MongoClient(uri)


def _get_filter_for_collection(q, collection_name):
    """Return time filter for a collection using its timestamp unit (from collection_timestamp_units)."""
    units = q.get("collection_timestamp_units", {})
    unit = units.get(collection_name, q.get("timestamp_unit", "milliseconds"))
    q_copy = {**q, "timestamp_unit": unit}
    filter_, _ = _apply_time_filter(q_copy)
    return filter_


def _apply_time_filter(q):
    """Filter: timestamp in [now - last_hours, now]. Returns (filter, since_sec_for_debug or None).
    Use 'timestamp_unit': 'seconds' or 'milliseconds'. Use 'timezone' (e.g. 'America/Denver' for MST/SLC)."""
    filter_ = dict(q.get("filter", {}))
    last_hours = q.get("last_hours")
    last_days = q.get("last_days")
    if last_hours is not None:
        hours = last_hours
    elif last_days is not None:
        hours = last_days * 24
    else:
        return filter_, None

    tz_name = q.get("timezone")
    if tz_name:
        tz = ZoneInfo(tz_name)
        now_local = datetime.now(tz)
        since_local = now_local - timedelta(hours=hours)
        since_sec = since_local.timestamp()
        now_sec = now_local.timestamp()
    else:
        now_sec = time.time()
        since_sec = now_sec - (hours * 3600)

    unit = q.get("timestamp_unit", "milliseconds")
    if unit == "milliseconds":
        since = int(since_sec * 1000)
        now_val = int(now_sec * 1000)
    else:
        since = int(since_sec)
        now_val = int(now_sec)

    ts_field = q.get("timestamp_field", "timestamp")
    filter_[ts_field] = {"$gte": since, "$lte": now_val}
    return filter_, since_sec


def _style_figure():
    """Apply professional styling to matplotlib figures."""
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica"],
        "font.size": 10,
        "axes.titlesize": 11,
        "axes.labelsize": 10,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.alpha": 0.4,
        "grid.linestyle": "-",
    })


def _plot_daily_report(participant_ids, collection_names, table, col_labels=None, time_label="last 24h", out_basename="daily_report_24h"):
    """One subplot per collection, each with its own count scale (collections have different frequencies)."""
    if not _HAS_MATPLOTLIB:
        print("  (install matplotlib to generate plot: pip install matplotlib)")
        return
    _style_figure()
    col_labels = col_labels or {}
    n_p = len(participant_ids)
    n_c = len(collection_names)
    if n_p == 0 or n_c == 0:
        return
    fig, axes = plt.subplots(n_c, 1, figsize=(max(10, n_p * 0.45), 2.75 * n_c), sharex=False)
    if n_c == 1:
        axes = [axes]
    x = np.arange(n_p)
    bar_color = "#0f766e"
    bar_edge = "#ffffff"
    for j, (coll, ax) in enumerate(zip(collection_names, axes)):
        counts = [table.get(pid, {}).get(coll, 0) for pid in participant_ids]
        bars = ax.bar(x, counts, color=bar_color, edgecolor=bar_edge, linewidth=0.8)
        ax.set_ylabel("Count", fontweight=500)
        ax.set_title(col_labels.get(coll, coll), fontweight=600, pad=8)
        ax.set_xticks(x)
        ax.set_xticklabels([str(pid) for pid in participant_ids], rotation=45, ha="right", fontsize=9)
        ax.set_xlim(-0.5, n_p - 0.5)
        ax.set_ylim(0, max(max(counts) * 1.05, 1) if counts else 1)
    fig.suptitle(f"Active participants ({time_label}) — counts per collection (each panel has its own scale)", fontsize=12, fontweight=600, y=1.02)
    plt.tight_layout()
    out_path = Path(f"{out_basename}.png")
    plt.savefig(out_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"  Plot saved: {out_path.absolute()}")


def _plot_daily_report_to_bytes(participant_ids, collection_names, table, col_labels=None, time_label="last 24h", out_basename="report"):
    """Same as _plot_daily_report but returns (png_bytes, filename_stem) for web server."""
    if not _HAS_MATPLOTLIB:
        return None, out_basename
    import io
    _style_figure()
    col_labels = col_labels or {}
    n_p = len(participant_ids)
    n_c = len(collection_names)
    if n_p == 0 or n_c == 0:
        return None, out_basename
    fig, axes = plt.subplots(n_c, 1, figsize=(max(10, n_p * 0.45), 2.75 * n_c), sharex=False)
    if n_c == 1:
        axes = [axes]
    x = np.arange(n_p)
    bar_color = "#0f766e"
    bar_edge = "#ffffff"
    for j, (coll, ax) in enumerate(zip(collection_names, axes)):
        counts = [table.get(pid, {}).get(coll, 0) for pid in participant_ids]
        ax.bar(x, counts, color=bar_color, edgecolor=bar_edge, linewidth=0.8)
        ax.set_ylabel("Count", fontweight=500)
        ax.set_title(col_labels.get(coll, coll), fontweight=600, pad=8)
        ax.set_xticks(x)
        ax.set_xticklabels([str(pid) for pid in participant_ids], rotation=45, ha="right", fontsize=9)
        ax.set_xlim(-0.5, n_p - 0.5)
        ax.set_ylim(0, max(max(counts) * 1.05, 1) if counts else 1)
    fig.suptitle(f"Active participants ({time_label}) — counts per collection (each panel has its own scale)", fontsize=12, fontweight=600, y=1.02)
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close()
    buf.seek(0)
    return buf.read(), out_basename


def run_query(client, q, db_name=None):
    name = q.get("name", "unnamed")
    action = q.get("action", "find")
    db_name = q.get("db") or db_name
    if not db_name and action not in ("list_databases",):
        print(f"[{name}] Skipped: need 'db' (and optionally 'collection') for this action")
        return

    db = client[db_name] if db_name else None
    coll_name = q.get("collection")
    collection = db[coll_name] if db is not None and coll_name else None

    # Use per-collection unit when collection_timestamp_units is set
    _units = q.get("collection_timestamp_units", {})
    _coll_for_unit = coll_name or (q.get("collections") or [None])[0]
    if _units and _coll_for_unit:
        _q_with_unit = {**q, "timestamp_unit": _units.get(_coll_for_unit, "milliseconds")}
        filter_, since_sec = _apply_time_filter(_q_with_unit)
    else:
        filter_, since_sec = _apply_time_filter(q)

    print(f"\n--- {name} ---")
    if since_sec is not None:
        tz_name = q.get("timezone")
        if q.get("last_days") is not None:
            tw_label = f"last {q['last_days']} days"
        elif q.get("last_hours") is not None:
            tw_label = "last 24h"
        else:
            tw_label = "time window"
        if tz_name:
            tz = ZoneInfo(tz_name)
            since_dt = datetime.fromtimestamp(since_sec, tz=tz)
            now_dt = datetime.fromtimestamp(time.time(), tz=tz)
            print(f"  only participants with data in {tw_label} (MST/SLC):")
            print(f"  from {since_dt.strftime('%Y-%m-%d %H:%M:%S %Z')} to {now_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        else:
            since_dt = datetime.fromtimestamp(since_sec, tz=timezone.utc)
            now_dt = datetime.fromtimestamp(time.time(), tz=timezone.utc)
            print(f"  participants with data in {tw_label}:")
            print(f"  from {since_dt.isoformat()} to {now_dt.isoformat()} UTC")

    try:
        if action == "distinct_combined" and db is not None:
            collections = q.get("collections", [])
            key = q.get("key")
            if not key or not collections:
                print("  Error: distinct_combined requires 'key' and 'collections' (list)")
                return
            all_ids = set()
            for coll_name in collections:
                coll = db[coll_name]
                coll_filter = _get_filter_for_collection(q, coll_name)
                ids = coll.distinct(key, coll_filter)
                all_ids.update(ids)
            id_list = sorted(all_ids)
            print(f"  set (no duplicates): {id_list}")
            for v in id_list:
                print(f"  {v}")
            print(f"  ({len(id_list)} active participants)")
            return
        if action == "participant_table" and db is not None:
            collections = q.get("collections", [])
            key = q.get("key")
            if not key or not collections:
                print("  Error: participant_table requires 'key' and 'collections' (list)")
                return
            # Per collection: count documents per participant (last 24h); each collection may use different timestamp unit
            table = {}
            all_ids = set()
            for coll_name in collections:
                coll = db[coll_name]
                coll_filter = _get_filter_for_collection(q, coll_name)
                pipeline = [
                    {"$match": coll_filter},
                    {"$group": {"_id": f"${key}", "count": {"$sum": 1}}},
                ]
                for doc in coll.aggregate(pipeline):
                    pid = doc["_id"]
                    all_ids.add(pid)
                    if pid not in table:
                        table[pid] = {}
                    table[pid][coll_name] = doc["count"]
            # Build rows: each participant, each column = collection count (0 if missing)
            col_width = max(14, max(len(c) for c in collections))
            id_width = max(20, max((len(str(pid)) for pid in all_ids), default=10))
            header = f"  {key:<{id_width}}" + "".join(f" {c:<{col_width}}" for c in collections)
            sep = "  " + "-" * (id_width + len(collections) * (col_width + 1))
            print(sep)
            print(header)
            print(sep)
            for pid in sorted(all_ids):
                row = table.get(pid, {})
                cells = "".join(f" {row.get(c, 0):<{col_width}}" for c in collections)
                print(f"  {str(pid):<{id_width}}{cells}")
            print(sep)
            return
        if action == "daily_report" and db is not None:
            collections = q.get("collections", REPORT_COLLECTIONS)
            key = q.get("key", "participantID")
            col_labels = q.get("report_col_labels", REPORT_COL_LABELS)
            if not collections:
                print("  Error: daily_report requires 'collections' (list)")
                return
            # Step 1: Active participants = distinct participantID per collection in TW, merged
            active_ids = set()
            for coll_name in collections:
                coll = db[coll_name]
                coll_filter = _get_filter_for_collection(q, coll_name)
                active_ids.update(coll.distinct(key, coll_filter))
            participant_ids = sorted(active_ids)
            # Step 2: Counts per participant per collection (restricted to TW)
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
            # Step 3: Print table (participantID | location | ENMO | surveys | logs | batteries)
            headers = [col_labels.get(c, c) for c in collections]
            col_width = max(10, max(len(h) for h in headers))
            id_width = max(18, max((len(str(pid)) for pid in participant_ids), default=10))
            header = f"  {key:<{id_width}}" + "".join(f" {h:>{col_width}}" for h in headers)
            sep = "  " + "-" * (id_width + len(collections) * (col_width + 1))
            print(sep)
            print(header)
            print(sep)
            for pid in participant_ids:
                row = table.get(pid, {})
                cells = "".join(f" {row.get(c, 0):>{col_width}}" for c in collections)
                print(f"  {str(pid):<{id_width}}{cells}")
            print(sep)
            if q.get("last_days") is not None:
                time_label = f"last {q['last_days']} days"
                out_basename = "weekly_report_7d"
            else:
                time_label = "last 24h"
                out_basename = "daily_report_24h"
            print(f"  Active participants ({time_label}): {len(participant_ids)}")
            # Step 4: Plot
            _plot_daily_report(participant_ids, collections, table, col_labels, time_label=time_label, out_basename=out_basename)
            return
        if action == "list_databases":
            for d in client.list_database_names():
                print(f"  {d}")
            return
        if action == "list_collections" and db is not None:
            for c in db.list_collection_names():
                print(f"  {c}")
            return
        if action == "count" and collection is not None:
            n = collection.count_documents(filter_)
            print(f"  count: {n}")
            return
        if action == "find" and collection is not None:
            cursor = collection.find(filter_).limit(q.get("limit", 10))
            for i, doc in enumerate(cursor):
                print(f"  [{i}] {json.dumps(doc, default=str, indent=2)}")
            return
        if action == "aggregate" and collection is not None:
            for doc in collection.aggregate(q.get("pipeline", [])):
                print(json.dumps(doc, default=str, indent=2))
            return
        if action == "distinct" and collection is not None:
            key = q.get("key")
            if not key:
                print("  Error: distinct action requires 'key' (e.g. 'participantID')")
                return
            values = sorted(collection.distinct(key, filter_))
            id_list = list(values)
            print(f"  list: {id_list}")
            for v in id_list:
                print(f"  {v}")
            print(f"  ({len(id_list)} active)")
            return
        print(f"  Unknown or incomplete action: {action}")
    except Exception as e:
        msg = str(e)
        if "Connection refused" in msg or "Errno 61" in msg:
            uri = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
            print(f"  Error: {e}")
            print(f"  Using MONGODB_URI from .env (or default). Edit .env to match your Compass connection string.")
            print(f"  Current: {uri.split('@')[-1] if '@' in uri else uri}")
        else:
            print(f"  Error: {e}")


def main():
    queries_file = sys.argv[1] if len(sys.argv) > 1 else None
    if queries_file and Path(queries_file).exists():
        with open(queries_file) as f:
            queries = json.load(f)
        if not isinstance(queries, list):
            queries = [queries]
    else:
        queries = QUERIES

    client = get_client()
    default_db = os.environ.get("MONGODB_DEFAULT_DB")
    for q in queries:
        run_query(client, q, db_name=default_db)
    print("\nDone.")


if __name__ == "__main__":
    main()

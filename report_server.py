#!/usr/bin/env python3
"""
Web server for the active-participants report. Run: python report_server.py
Open the HTML page, choose time window, click Run report; view table and plot, download CSV and PNG.

Security: Uses safe defaults (no debug, bind 127.0.0.1). CORS and optional API key
are configured via environment variables. See README.
"""

import base64
import os
import sys
import traceback
from datetime import datetime

from dotenv import load_dotenv

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

load_dotenv()
if getattr(sys, "frozen", False):
    app_dir = os.path.dirname(sys.executable)
    load_dotenv(os.path.join(app_dir, ".env"))
    load_dotenv(os.path.join(app_dir, "config.env"))  # visible name in zip

try:
    from flask import Flask, send_file, request, jsonify
except ImportError:
    print("Install Flask: pip install flask")
    raise

try:
    from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure
except ImportError:
    ServerSelectionTimeoutError = ConnectionFailure = Exception  # no-op if pymongo not installed

from mongodb_query import (
    get_client,
    _get_filter_for_collection,
    REPORT_COLLECTIONS,
    REPORT_COL_LABELS,
    REPORT_DISPLAY_ORDER,
    COLLECTION_TIMESTAMP_UNITS,
    BATTERY_ALERT_THRESHOLD,
    PHONE_BATTERY_ALERT_THRESHOLD,
    RED_FLAG_WINDOW_START_HOUR,
    RED_FLAG_WINDOW_END_HOUR,
    RED_FLAG_MIN_DURATION_SEC,
    RED_FLAG_MAX_GAP_SEC,
    ENMO_NONWEAR_THRESHOLD_G,
    ENMO_NONWEAR_MIN_CONSECUTIVE,
    ENMO_NONWEAR_MAX_SPIKE_MINUTES,
    ENMO_FIELD,
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


def _red_flag_1h_low_wristband(pid_to_timestamps_ms, timezone_name):
    """Given participant_id -> list of timestamps (ms) for low wristband battery records,
    return (flagged_set, pid_to_count). flagged_set = PIDs with at least one run >= 1h;
    pid_to_count = number of distinct contiguous runs >= 1h within 9:00 AM–10:00 PM local."""
    tz = ZoneInfo(timezone_name)
    flagged = set()
    pid_to_count = {}
    max_gap_ms = RED_FLAG_MAX_GAP_SEC * 1000
    min_duration_ms = RED_FLAG_MIN_DURATION_SEC * 1000
    for pid, ts_list in pid_to_timestamps_ms.items():
        if not ts_list:
            pid_to_count[pid] = 0
            continue
        # Keep only timestamps that fall in 9 AM – 10 PM local
        in_window = []
        for ts_ms in ts_list:
            try:
                dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=tz)
                if RED_FLAG_WINDOW_START_HOUR <= dt.hour < RED_FLAG_WINDOW_END_HOUR:
                    in_window.append(ts_ms)
            except (TypeError, ValueError, OSError):
                continue
        in_window.sort()
        if not in_window:
            pid_to_count[pid] = 0
            continue
        # Count contiguous runs that meet the 1h threshold
        run_count = 0
        i = 0
        while i < len(in_window):
            run_start = in_window[i]
            run_end = run_start
            j = i + 1
            while j < len(in_window) and (in_window[j] - run_end) <= max_gap_ms:
                run_end = in_window[j]
                j += 1
            if (run_end - run_start) >= min_duration_ms:
                run_count += 1
                flagged.add(pid)
            i = j
        pid_to_count[pid] = run_count
    return flagged, pid_to_count


def _compute_non_wear_episodes(db, q, participant_ids, key, enmo_field, threshold_g, min_consecutive, max_spike):
    """From userenmos: 1-min average ENMO; inactive if mean < threshold; non-wear = >= min_consecutive
    consecutive inactive minutes, allowing up to max_spike consecutive active minutes without reset.
    Returns dict participant_id -> number of non-wear episodes."""
    coll = db["userenmos"]
    coll_filter = _get_filter_for_collection(q, "userenmos")
    pipeline = [
        {"$match": coll_filter},
        {"$group": {
            "_id": {"pid": f"${key}", "minute": {"$floor": {"$divide": ["$timestamp", 60]}}},
            "mean_enmo": {"$avg": f"${enmo_field}"},
        }},
        {"$sort": {"_id.pid": 1, "_id.minute": 1}},
    ]
    # Group by pid: list of (minute, mean_enmo) sorted by minute
    pid_to_minutes = {}
    for doc in coll.aggregate(pipeline):
        pid = doc["_id"]["pid"]
        minute = doc["_id"]["minute"]
        mean_enmo = doc.get("mean_enmo")
        if mean_enmo is None:
            continue
        pid_to_minutes.setdefault(pid, []).append((minute, mean_enmo))

    out = {}
    for pid in participant_ids:
        out[pid] = 0
    for pid, minutes_list in pid_to_minutes.items():
        if pid not in out:
            out[pid] = 0
        if not minutes_list:
            continue
        # Sort by minute and dedupe (same minute could appear if multiple groups)
        by_minute = {}
        for m, v in minutes_list:
            by_minute[m] = v
        minutes_sorted = sorted(by_minute.items())
        consecutive_inactive = 0
        consecutive_spikes = 0
        episode_count = 0
        counted_this_run = False
        for _minute, mean_enmo in minutes_sorted:
            inactive = mean_enmo < threshold_g
            if inactive:
                consecutive_inactive += 1
                consecutive_spikes = 0
                if consecutive_inactive >= min_consecutive and not counted_this_run:
                    episode_count += 1
                    counted_this_run = True
            else:
                if consecutive_spikes >= max_spike:
                    consecutive_inactive = 0
                    consecutive_spikes = 0
                    counted_this_run = False
                else:
                    consecutive_spikes += 1
        out[pid] = episode_count
    return out


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
    include_battery_alerts=False,
    include_phone_battery_alerts=False,
    include_red_flag=True,
    include_left_wristband_mac=True,
    include_right_wristband_mac=True,
    include_phone_id=True,
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
        start_dt = datetime.fromtimestamp(start_ts, tz=tz)
        end_dt = datetime.fromtimestamp(end_ts, tz=tz)
        time_label = (
            start_dt.strftime("%Y-%m-%d")
            + "_to_"
            + end_dt.strftime("%Y-%m-%d")
        )
        # Start with minutes; end with day, hour, minute, and timezone (e.g. MST)
        display_label = (
            start_dt.strftime("%Y-%m-%d %H:%M")
            + " to "
            + end_dt.strftime("%b %d, %H:%M %Z")
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

    # Step 2a: Non-wear episodes from userenmos (1-min mean ENMO < threshold, ≥60 consecutive inactive, up to 2 spikes allowed)
    if "userenmos" in coll_list:
        for pid in participant_ids:
            table.setdefault(pid, {})["non_wear_episodes"] = 0
        pid_to_non_wear = _compute_non_wear_episodes(
            db, q, participant_ids, key,
            ENMO_FIELD, ENMO_NONWEAR_THRESHOLD_G,
            ENMO_NONWEAR_MIN_CONSECUTIVE, ENMO_NONWEAR_MAX_SPIKE_MINUTES,
        )
        for pid, count in pid_to_non_wear.items():
            if pid in table:
                table[pid]["non_wear_episodes"] = count

    # Step 2b: Log event counts (for compliance monitoring) when Logs is selected
    log_event_columns = [
        ("log_disconnects", "disconnect-wristband-to-app"),
        ("log_data_collection_disabled", "Data Collection Disabled"),
        ("log_survey_expired", "Activity Survey Expired"),
        ("log_pa_denied", "PA_denied"),
        ("log_pa_ema_notifications", "PA_EMA_new-notification"),
    ]
    if "userlogs" in coll_list:
        for pid in participant_ids:
            for col_key, _ in log_event_columns:
                table.setdefault(pid, {})[col_key] = 0
            table.setdefault(pid, {})["log_daily_timed_ema"] = 0
        logs_coll = db["userlogs"]
        logs_filter = _get_filter_for_collection(q, "userlogs")
        for col_key, event_name in log_event_columns:
            for doc in logs_coll.aggregate([
                {"$match": {**logs_filter, "eventName": event_name}},
                {"$group": {"_id": f"${key}", "count": {"$sum": 1}}},
            ]):
                pid = doc["_id"]
                if pid in table:
                    table[pid][col_key] = doc["count"]
        # Daily timed EMA: morning + afternoon + evening survey triggers (one column, summed)
        for doc in logs_coll.aggregate([
            {"$match": {**logs_filter, "eventName": {"$in": ["morning_survey_trigger", "afternoon_survey_trigger", "evening_survey_trigger"]}}},
            {"$group": {"_id": f"${key}", "count": {"$sum": 1}}},
        ]):
            pid = doc["_id"]
            if pid in table:
                table[pid]["log_daily_timed_ema"] = doc["count"]

    # Step 3: Battery alerts from userbatteries (left/right below threshold) + wristband MAC(s)
    battery_alert_columns = []
    if "userbatteries" in coll_list and include_battery_alerts:
        for pid in participant_ids:
            table.setdefault(pid, {})["battery_alerts_left"] = 0
            table.setdefault(pid, {})["left_wristband_mac"] = ""
            table.setdefault(pid, {})["battery_alerts_right"] = 0
            table.setdefault(pid, {})["right_wristband_mac"] = ""
        bat_filter = _get_filter_for_collection(q, "userbatteries")
        bat_coll = db["userbatteries"]
        thresh = BATTERY_ALERT_THRESHOLD
        for doc in bat_coll.aggregate([
            {"$match": {**bat_filter, "leftwristbandBatteryLevel": {"$lt": thresh}}},
            {"$group": {"_id": {"pid": "$" + key, "mac": "$leftwristbandMAC"}, "count": {"$sum": 1}}},
        ]):
            pid = doc["_id"]["pid"]
            mac = doc["_id"].get("mac") or ""
            cnt = doc["count"]
            if pid in table and mac:
                table[pid]["battery_alerts_left"] = table[pid].get("battery_alerts_left", 0) + cnt
                existing = (table[pid].get("left_wristband_mac") or "").strip()
                table[pid]["left_wristband_mac"] = (existing + ", " + mac).strip(", ") if existing else mac
        for doc in bat_coll.aggregate([
            {"$match": {**bat_filter, "rightwristbandBatteryLevel": {"$lt": thresh}}},
            {"$group": {"_id": {"pid": "$" + key, "mac": "$rightwristbandMAC"}, "count": {"$sum": 1}}},
        ]):
            pid = doc["_id"]["pid"]
            mac = doc["_id"].get("mac") or ""
            cnt = doc["count"]
            if pid in table and mac:
                table[pid]["battery_alerts_right"] = table[pid].get("battery_alerts_right", 0) + cnt
                existing = (table[pid].get("right_wristband_mac") or "").strip()
                table[pid]["right_wristband_mac"] = (existing + ", " + mac).strip(", ") if existing else mac
        # Red flag: 1h continuously low wristband (left or right < 20%) between 9 AM and 10 PM local
        for pid in participant_ids:
            table.setdefault(pid, {})["red_flag_1h_low_wristband"] = ""
        low_filter = {
            **bat_filter,
            "$or": [
                {"leftwristbandBatteryLevel": {"$lt": thresh}},
                {"rightwristbandBatteryLevel": {"$lt": thresh}},
            ],
        }
        pid_to_ts = {}
        for doc in bat_coll.aggregate([
            {"$match": low_filter},
            {"$group": {"_id": "$" + key, "timestamps": {"$push": "$timestamp"}}},
        ]):
            pid = doc["_id"]
            pid_to_ts[pid] = [int(t) for t in (doc.get("timestamps") or []) if t is not None]
        _, pid_to_flag_count = _red_flag_1h_low_wristband(pid_to_ts, timezone_name)
        for pid in participant_ids:
            table.setdefault(pid, {})["red_flag_1h_low_wristband"] = pid_to_flag_count.get(pid, 0)
        battery_alert_columns = ["battery_alerts_left", "left_wristband_mac", "battery_alerts_right", "right_wristband_mac", "red_flag_1h_low_wristband"]

    # Step 4: Phone battery alerts (< 10%) and phone ID from userbatteries
    phone_alert_columns = []
    if "userbatteries" in coll_list and include_phone_battery_alerts:
        bat_filter = _get_filter_for_collection(q, "userbatteries")
        bat_coll = db["userbatteries"]
        phone_thresh = PHONE_BATTERY_ALERT_THRESHOLD
        for pid in participant_ids:
            table.setdefault(pid, {})["phone_id"] = ""
            table.setdefault(pid, {})["phone_battery_alerts"] = 0
        for doc in bat_coll.aggregate([
            {"$match": {**bat_filter, "phoneBatteryLevel": {"$lt": phone_thresh}}},
            {"$group": {"_id": "$" + key, "count": {"$sum": 1}}},
        ]):
            pid = doc["_id"]
            if pid in table:
                table[pid]["phone_battery_alerts"] = doc["count"]
        for doc in bat_coll.aggregate([
            {"$match": bat_filter},
            {"$group": {"_id": "$" + key, "phoneIDs": {"$addToSet": "$phoneID"}}},
        ]):
            pid = doc["_id"]
            ids = doc.get("phoneIDs") or []
            ids = [str(x).strip() for x in ids if x is not None and str(x).strip()]
            # Show only last 4 characters of each phone ID
            ids = [x[-4:] if len(x) >= 4 else x for x in ids]
            if pid in table and ids:
                table[pid]["phone_id"] = ", ".join(sorted(set(ids)))
        phone_alert_columns = ["phone_id", "phone_battery_alerts"]

    log_event_col_list = (
        ["log_disconnects", "log_data_collection_disabled", "log_survey_expired", "log_pa_denied", "log_pa_ema_notifications", "log_daily_timed_ema"]
        if "userlogs" in coll_list
        else []
    )
    combined = set(coll_list) | set(log_event_col_list) | set(battery_alert_columns) | set(phone_alert_columns)
    if "userenmos" in coll_list:
        combined.add("non_wear_episodes")
    if not include_red_flag:
        combined.discard("red_flag_1h_low_wristband")
    if not include_left_wristband_mac:
        combined.discard("left_wristband_mac")
    if not include_right_wristband_mac:
        combined.discard("right_wristband_mac")
    if not include_phone_id:
        combined.discard("phone_id")
    out_coll_list = [c for c in REPORT_DISPLAY_ORDER if c in combined]
    run_ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    return participant_ids, table, display_label, time_label, run_ts, out_coll_list


def _col_label(c):
    """Display label for a column."""
    return REPORT_COL_LABELS.get(c, c)


def _safe_mean_sd(values):
    """Return (mean, sd) for a list of numbers; (None, None) if empty or all non-numeric.
    Uses sample standard deviation (divide by n-1 when n>=2) for publication consistency."""
    nums = [float(x) for x in values if x is not None and str(x).strip() != ""]
    try:
        n = len(nums)
        if n == 0:
            return None, None
        mean = sum(nums) / n
        if n < 2:
            return round(mean, 4), 0.0
        variance = sum((x - mean) ** 2 for x in nums) / (n - 1)
        sd = (variance ** 0.5) if variance >= 0 else 0.0
        return round(mean, 4), round(sd, 4)
    except (TypeError, ValueError):
        return None, None


def compute_study_summary(participant_ids, table, display_label, col_labels, collections_queried=None):
    """
    Compute publication-ready summary stats from the report table.
    collections_queried: list of collection keys actually included in the report (e.g. from run_report).
      For collections in REPORT_COLLECTIONS but not in collections_queried, mean/sd are not computed
      and "queried": False is set so the UI can show "Not queried" instead of 0.
    Returns dict with stats and a list of {metric_name, value, description} for export.
    """
    n = len(participant_ids)
    if n == 0:
        return {"metrics_for_export": [], "n_participants": 0}

    # Data collections we report counts for (all known collections)
    data_collections = [c for c in REPORT_COLLECTIONS if c in REPORT_COL_LABELS]
    queried_set = set(collections_queried) if collections_queried else set(data_collections)
    mean_sd_per_collection = {}
    for coll in data_collections:
        label = col_labels.get(coll, coll)
        if coll not in queried_set:
            mean_sd_per_collection[coll] = {"label": label, "mean": None, "sd": None, "queried": False}
            continue
        counts = []
        for pid in participant_ids:
            v = table.get(pid, {}).get(coll, 0)
            try:
                counts.append(int(v) if v != "" else 0)
            except (TypeError, ValueError):
                counts.append(0)
        mean_val, sd_val = _safe_mean_sd(counts)
        mean_sd_per_collection[coll] = {"label": label, "mean": mean_val, "sd": sd_val, "queried": True}

    # Response rate: submitted surveys / daily timed EMA triggers (per participant, then mean/sd)
    response_rates = []
    for pid in participant_ids:
        row = table.get(pid, {})
        denom = row.get("log_daily_timed_ema") or row.get("log_pa_ema_notifications") or 0
        try:
            denom = int(denom)
        except (TypeError, ValueError):
            denom = 0
        num = row.get("surveys", 0)
        try:
            num = int(num)
        except (TypeError, ValueError):
            num = 0
        if denom > 0:
            response_rates.append(num / denom)
    response_rate_mean, response_rate_sd = _safe_mean_sd(response_rates)
    def _int(v):
        try:
            return int(v) if v is not None and v != "" else 0
        except (TypeError, ValueError):
            return 0
    total_surveys = sum(_int(table.get(pid, {}).get("surveys")) for pid in participant_ids)
    total_triggers = sum(
        _int(table.get(pid, {}).get("log_daily_timed_ema") or table.get(pid, {}).get("log_pa_ema_notifications"))
        for pid in participant_ids
    )
    overall_response_rate = (total_surveys / total_triggers) if total_triggers > 0 else None

    # Red flag count
    n_red_flag = 0
    for pid in participant_ids:
        v = table.get(pid, {}).get("red_flag_1h_low_wristband", 0)
        try:
            if (v or 0) > 0:
                n_red_flag += 1
        except (TypeError, ValueError):
            pass
    pct_red_flag = round(100.0 * n_red_flag / n, 1) if n else 0

    # No/minimal data: location, ENMO, and surveys all zero
    n_no_data = 0
    for pid in participant_ids:
        row = table.get(pid, {})
        loc = row.get("userlocations", 0) or 0
        enmo = row.get("userenmos", 0) or 0
        sur = row.get("surveys", 0) or 0
        try:
            loc, enmo, sur = int(loc), int(enmo), int(sur)
        except (TypeError, ValueError):
            pass
        if loc == 0 and enmo == 0 and sur == 0:
            n_no_data += 1
    pct_no_data = round(100.0 * n_no_data / n, 1) if n else 0

    # Build export list: metric_name, value, description
    metrics_for_export = [
        ("n_participants", str(n), "Number of participants with at least one record in the selected time window"),
        ("date_range", display_label, "Time window of the report (e.g. last 7 days or custom range)"),
        ("response_rate_mean", str(response_rate_mean) if response_rate_mean is not None else "N/A", "Mean EMA/survey response rate (submitted / triggers) per participant"),
        ("response_rate_sd", str(response_rate_sd) if response_rate_sd is not None else "N/A", "SD of per-participant response rate"),
        ("response_rate_overall", str(round(overall_response_rate, 4)) if overall_response_rate is not None else "N/A", "Overall response rate (total submitted / total triggers)"),
        ("n_with_red_flag", str(n_red_flag), "Number of participants with ≥1 red flag (wristband low 1h+ 9AM–10PM)"),
        ("pct_with_red_flag", str(pct_red_flag) + "%", "Percent of participants with ≥1 red flag"),
        ("n_no_or_minimal_data", str(n_no_data), "Number of participants with no location, ENMO, or survey records in window"),
        ("pct_no_or_minimal_data", str(pct_no_data) + "%", "Percent of participants with no/minimal data"),
    ]
    for coll in data_collections:
        info = mean_sd_per_collection.get(coll, {})
        label = info.get("label", coll)
        mean_val, sd_val = info.get("mean"), info.get("sd")
        queried = info.get("queried", True)
        if not queried:
            metrics_for_export.append((f"mean_{coll}", "Not queried", f"{label} was not selected for this report."))
            metrics_for_export.append((f"sd_{coll}", "Not queried", f"{label} was not selected for this report."))
        else:
            metrics_for_export.append((
                f"mean_{coll}",
                str(mean_val) if mean_val is not None else "N/A",
                f"Mean count of {label} records per participant",
            ))
            metrics_for_export.append((
                f"sd_{coll}",
                str(sd_val) if sd_val is not None else "N/A",
                f"SD of {label} count per participant",
            ))

    return {
        "n_participants": n,
        "date_range": display_label,
        "response_rate_mean": response_rate_mean,
        "response_rate_sd": response_rate_sd,
        "response_rate_overall": overall_response_rate,
        "n_valid_response_rate": len(response_rates),
        "mean_sd_per_collection": mean_sd_per_collection,
        "n_red_flag": n_red_flag,
        "pct_red_flag": pct_red_flag,
        "n_no_data": n_no_data,
        "pct_no_data": pct_no_data,
        "metrics_for_export": [{"metric_name": m[0], "value": m[1], "description": m[2]} for m in metrics_for_export],
    }


def table_to_rows(participant_ids, table, collections):
    """Return [header_row, ...data_rows] for CSV and HTML table."""
    headers = ["participantID"] + [_col_label(c) for c in collections]
    text_cols = {"left_wristband_mac", "right_wristband_mac", "phone_id"}
    rows = [headers]
    for pid in participant_ids:
        row = table.get(pid, {})
        def _cell(c):
            default = "" if c in text_cols else 0
            return row.get(c, default)
        rows.append([str(pid)] + [_cell(c) for c in collections])
    return rows


_ROOT = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


@app.route("/")
def index():
    return send_file(os.path.join(_ROOT, "report_app.html"))


@app.route("/report_app.html")
def report_app():
    return send_file(os.path.join(_ROOT, "report_app.html"))


@app.route("/help")
@app.route("/help.html")
def help_page():
    return send_file(os.path.join(_ROOT, "help.html"))


@app.route("/cat-loader.png")
def cat_loader():
    path = os.path.join(_ROOT, "cat-loader.png")
    if os.path.isfile(path):
        return send_file(path, mimetype="image/png")
    return "", 404


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
    include_battery_alerts = data.get("include_battery_alerts", False)
    include_phone_battery_alerts = data.get("include_phone_battery_alerts", False)
    include_red_flag = data.get("include_red_flag", True)
    include_left_wristband_mac = data.get("include_left_wristband_mac", True)
    include_right_wristband_mac = data.get("include_right_wristband_mac", True)
    include_phone_id = data.get("include_phone_id", True)
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
            include_battery_alerts=include_battery_alerts,
            include_phone_battery_alerts=include_phone_battery_alerts,
            include_red_flag=include_red_flag,
            include_left_wristband_mac=include_left_wristband_mac,
            include_right_wristband_mac=include_right_wristband_mac,
            include_phone_id=include_phone_id,
        )
    except (ServerSelectionTimeoutError, ConnectionFailure) as e:
        return jsonify({
            "error": "Could not connect to the database. Check that config.env has the correct MONGODB_URI and that MongoDB (or your SSH tunnel) is running.",
            "detail": str(e),
        }), 503
    except Exception as e:
        err_msg = str(e)
        # Fallback: treat connection-refused / timeout as 503 (frozen app may raise different type)
        if "Connection refused" in err_msg or "ServerSelectionTimeoutError" in type(e).__name__ or "ConnectionFailure" in type(e).__name__:
            return jsonify({
                "error": "Could not connect to the database. Check that config.env has the correct MONGODB_URI and that MongoDB (or your SSH tunnel) is running.",
                "detail": err_msg,
            }), 503
        traceback.print_exc()
        return jsonify({"error": err_msg}), 500
    rows = table_to_rows(participant_ids, table, coll_list)
    # Human-readable filename: start with minutes, end with day hour minute MST (no Denver after MST)
    generated_readable = run_ts[:10] + " " + run_ts[11:13] + "-" + run_ts[13:]  # YYYY-MM-DD HH-MM
    range_readable = display_label  # e.g. "2026-02-10 00:00 to Feb 15, 23:59 MST" or "last 24 hours"
    base_readable = f"report generated at {generated_readable} {range_readable}"
    csv_filename = base_readable + ".csv"
    plot_filename = base_readable + ".png"
    col_labels = {**REPORT_COL_LABELS}
    plot_collections = [c for c in coll_list if c not in (
        "left_wristband_mac", "right_wristband_mac", "phone_id", "red_flag_1h_low_wristband",
        "log_disconnects", "log_data_collection_disabled", "log_survey_expired", "log_pa_denied",
        "log_pa_ema_notifications", "log_daily_timed_ema",
    )]
    raw_plot_type = (data.get("plot_type") or data.get("visualization_type") or "stacked").strip().lower()
    plot_type = raw_plot_type if raw_plot_type in ("bar", "horizontal_bar", "stacked") else "stacked"
    try:
        plot_bytes, _ = _plot_daily_report_to_bytes(
            participant_ids, plot_collections, table,
            col_labels=col_labels,
            time_label=display_label,
            out_basename="report",
            plot_type=plot_type,
        )
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Plot failed: {e}"}), 500
    plot_b64 = base64.b64encode(plot_bytes).decode("utf-8") if plot_bytes else None
    plot_type_labels = {"bar": "Bar chart", "horizontal_bar": "Horizontal bar", "stacked": "Stacked bar"}
    payload = {
        "table": rows,
        "participant_ids": participant_ids,
        "time_label": display_label,
        "run_timestamp": run_ts,
        "csv_filename": csv_filename,
        "plot_filename": plot_filename,
        "plot_base64": plot_b64,
        "plot_type": plot_type,
        "plot_type_label": plot_type_labels.get(plot_type, "Bar chart"),
    }
    if plot_type == "stacked":
        payload["chart_data"] = {
            "labels": participant_ids,
            "datasets": [
                {
                    "label": col_labels.get(coll, coll),
                    "data": [table.get(pid, {}).get(coll, 0) for pid in participant_ids],
                }
                for coll in plot_collections
            ],
        }
    payload["study_summary"] = compute_study_summary(participant_ids, table, display_label, col_labels, coll_list)
    return jsonify(payload)


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=DEBUG)

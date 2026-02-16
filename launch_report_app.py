#!/usr/bin/env python3
"""
Launcher for MotionPI Report: starts the server and opens the default browser.
Used as the entry point when packaged with PyInstaller so users can double-click
one app without running Python or the server manually.
"""

import os
import sys
import time
import webbrowser
import threading
import urllib.request
import urllib.error
import traceback

# Import after potential .env load from report_server
import report_server

def _log_path():
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "MotionPI_Report_log.txt")
    return os.path.join(os.path.expanduser("~"), "MotionPI_Report_log.txt")

def _log(msg):
    try:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass

def run_server():
    while True:
        try:
            report_server.app.run(
                host=report_server.HOST,
                port=report_server.PORT,
                debug=False,
                use_reloader=False,
                threaded=True,
            )
            break
        except Exception as e:
            _log(time.strftime("%Y-%m-%d %H:%M:%S ") + "Server error: " + str(e))
            _log(traceback.format_exc())
            time.sleep(5)

def wait_for_server(url, timeout_sec=45, interval_sec=0.5):
    """Wait until the server responds with 200 or timeout."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(url, method="GET")
            urllib.request.urlopen(req, timeout=2)
            return True
        except (OSError, urllib.error.URLError):
            time.sleep(interval_sec)
    return False

def main():
    if getattr(sys, "frozen", False):
        app_dir = os.path.dirname(sys.executable)
        try:
            os.chdir(app_dir)
        except Exception:
            pass
    server_thread = threading.Thread(target=run_server, daemon=False)
    server_thread.start()

    url = f"http://{report_server.HOST}:{report_server.PORT}/"
    if wait_for_server(url):
        webbrowser.open(url)
    else:
        _log(time.strftime("%Y-%m-%d %H:%M:%S ") + "Server did not start in time. Check " + _log_path())

    try:
        server_thread.join()
    except KeyboardInterrupt:
        pass
    # If server thread exited unexpectedly, keep process alive and log so user can send the log
    if server_thread.is_alive():
        return
    _log(time.strftime("%Y-%m-%d %H:%M:%S ") + "Server thread stopped. See above for errors.")
    while True:
        time.sleep(3600)

if __name__ == "__main__":
    main()

MotionPI Report — ready to run
-----------------------------
1. Double-click "MotionPI Report" (first time: right-click → Open if macOS blocks it).
2. Your browser will open. Choose time range and data sources, then click "Run report".

Before first run, open "config.env" and set:
MONGODB_URI=mongodb://admin:YOUR_MONGODB_PASSWORD@127.0.0.1:27017/?authSource=admin&directConnection=true

Keep "config.env" in this folder next to the app. If your setup uses an SSH tunnel, keep the tunnel terminal open while running reports.

Which zip to use:
- Intel Macs (e.g. 2019 MacBook Pro): use MotionPI_Report_Mac_Intel.zip.
- Apple Silicon (M1/M2/M3): use MotionPI_Report_Mac.zip.

# Building MotionPI Report for Intel Mac and Windows

The default **MotionPI_Report_Mac.zip** is built for **Apple Silicon (M1/M2/M3)**. Users with **Intel Macs** or **Windows** need a different build.

---

## Intel Mac (e.g. 2019 MacBook Pro)

The app must be built as **x86_64**. Options:

### Option A: Build on an Intel Mac
On a Mac with an Intel processor:
```bash
cd /path/to/motionpi-surveillance
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install pyinstaller
pyinstaller --clean MotionPI_Report.spec
# Then copy env.dist → dist/config.env, README_for_zip.txt → dist/README.txt
# Zip dist/MotionPI Report, config.env, README.txt → MotionPI_Report_Mac_Intel.zip
```

### Option B: Build on Apple Silicon for Intel (x86_64)
You need a **x86_64** Python (running under Rosetta). Example:
1. Install Python for Mac OS X 64-bit from [python.org](https://www.python.org/downloads/) (choose the Intel installer if you have both).
2. Or with Homebrew under Rosetta: `arch -x86_64 /usr/local/bin/brew install python` (then use that Python to create a venv and run PyInstaller).
3. In that x86_64 environment: create venv, `pip install -r requirements.txt pyinstaller`, then `pyinstaller --clean MotionPI_Report.spec`.

### Option C: Run from Python (no app build)
On the Intel Mac, they can run the report **without** the packaged app:
1. Install Python 3, then: `pip install -r requirements.txt`
2. Copy the project folder (or clone the repo). Put `config.env` in the folder with `MONGODB_URI=mongodb://YOUR_DB_HOST:27017`.
3. Run: `python launch_report_app.py` (or `python report_server.py` and open http://127.0.0.1:5050 in the browser).

This works on any Mac (Intel or Apple Silicon) and avoids the “bad CPU type” issue.

---

## Windows (e.g. lab Dell laptop)

Build **on a Windows machine** (the Dell or any Windows PC):

1. Install Python 3 from [python.org](https://www.python.org/downloads/) (add to PATH).
2. Open Command Prompt or PowerShell in the project folder:
   ```
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   pip install pyinstaller
   pyinstaller --clean MotionPI_Report_win.spec
   ```
3. Copy `env.dist` to `dist\config.env` and `README_for_zip.txt` to `dist\README.txt`.
4. Zip the contents of `dist`: **MotionPI Report.exe**, **config.env**, **README.txt** → e.g. **MotionPI_Report_Windows.zip**.

Users on Windows unzip, keep config.env next to the .exe, and double-click **MotionPI Report.exe**.

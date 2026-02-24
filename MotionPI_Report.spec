# PyInstaller spec for MotionPI Report — double-click app that starts server + opens browser.
# Build: pyinstaller MotionPI_Report.spec
# Output: dist/MotionPI Report.app (macOS) or dist/MotionPI Report/ (Windows)

import sys

block_cipher = None

# Data files to bundle (HTML and assets at _MEIPASS root for send_file)
datas = [('report_app.html', '.'), ('help.html', '.'), ('cat-loader.png', '.')]

# Modules PyInstaller may not detect
hiddenimports = [
    'flask',
    'pymongo',
    'matplotlib',
    'matplotlib.backends.backend_agg',
    'python_dotenv',
    'mongodb_query',
    'report_server',
    'zoneinfo',
]

# Python 3.8 has no zoneinfo; backports.zoneinfo is optional
if sys.version_info < (3, 9):
    hiddenimports.append('backports.zoneinfo')

a = Analysis(
    ['launch_report_app.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='MotionPI Report',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,   # No terminal window (double-click app)
    disable_windowed_traceback=False,
    argv_emulation=True,   # macOS: open documents from Finder
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

#!/bin/bash
# Build MotionPI Report for Intel (x86_64) Macs.
# Run this on an Apple Silicon Mac to produce MotionPI_Report_Mac_Intel.zip.
# Intel Mac users get "bad CPU type in executable" with the arm64 build — use this zip instead.

set -e
cd "$(dirname "$0")"

# Use system Python under Rosetta so we get x86_64 (PATH python3 is often arm64 on Apple Silicon)
PY_X86="arch -x86_64 /usr/bin/python3"
if ! $PY_X86 -c "import sys; sys.exit(0)" 2>/dev/null; then
  PY_X86="arch -x86_64 python3"
fi
INTEL_VENV="venv_intel"

# Ensure we have an x86_64 venv (remove and recreate if it's arm64)
if [[ -d "$INTEL_VENV" ]]; then
  ARCH=$("$INTEL_VENV/bin/python3" -c "import platform; print(platform.machine())" 2>/dev/null || true)
  if [[ "$ARCH" != "x86_64" ]]; then
    echo "Removing existing venv_intel (was $ARCH, need x86_64)..."
    rm -rf "$INTEL_VENV"
  fi
fi
if [[ ! -d "$INTEL_VENV" ]]; then
  echo "Creating Intel (x86_64) virtual environment..."
  if ! $PY_X86 -m venv "$INTEL_VENV" 2>/dev/null; then
    echo "Could not create Intel venv. Install Rosetta 2 (Software Update). Then try:"
    echo "  arch -x86_64 /usr/bin/python3 --version"
    echo "If that fails, install Intel Homebrew and Python:"
    echo "  arch -x86_64 /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    echo "  arch -x86_64 /usr/local/bin/brew install python@3.11"
    exit 1
  fi
fi

PY_VENV="$INTEL_VENV/bin/python3"
PIP_VENV="$INTEL_VENV/bin/pip"
ARCH=$(arch -x86_64 "$PY_VENV" -c "import platform; print(platform.machine())")
if [[ "$ARCH" != "x86_64" ]]; then
  echo "Expected x86_64 in venv_intel, got: $ARCH. Remove venv_intel and re-run."
  exit 1
fi

echo "Installing/updating dependencies (Intel)..."
arch -x86_64 "$PIP_VENV" install --quiet --upgrade pip
arch -x86_64 "$PIP_VENV" install --quiet -r requirements.txt
arch -x86_64 "$PIP_VENV" install --quiet pyinstaller

echo "Building app for Intel (x86_64)..."
arch -x86_64 "$INTEL_VENV/bin/pyinstaller" --clean MotionPI_Report.spec

echo "Adding config and README..."
cp env.dist dist/config.env
cp README_for_zip.txt dist/README.txt

echo "Creating Intel zip..."
cd dist
zip -r ../MotionPI_Report_Mac_Intel.zip "MotionPI Report" config.env README.txt
cd ..

echo "Done. Send MotionPI_Report_Mac_Intel.zip to Intel Mac users."
echo "Verify: file dist/\"MotionPI Report\" should show: Mach-O 64-bit executable x86_64"

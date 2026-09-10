#!/usr/bin/env bash
# Build a UNIVERSAL2 "Timeline Reader.app" — one bundle that runs natively on
# both Apple Silicon (arm64) and Intel (x86_64) Macs.
#
# How it works: PyInstaller emits a binary for the building Python's
# architecture, so a universal2 build needs a universal2 Python plus universal2
# native wheels. macOS ships a universal2 Python at /usr/bin/python3, and
# PySide6/shiboken publish universal2 wheels — so we build with that.
#
# Caveat: /usr/bin/python3 is 3.9, and PySide6 6.11 dropped 3.9, so the
# universal build pins PySide6 < 6.11 (6.10.x). The normal ./build_app.sh keeps
# using the arm64 dev venv (newer PySide6) for local runs.
set -euo pipefail
cd "$(dirname "$0")"

VENV=.venv-universal
PY=/usr/bin/python3

if [ ! -x "$PY" ]; then
  echo "Need macOS system python at $PY (universal2). Install the Command Line Tools." >&2
  exit 1
fi

if [ ! -d "$VENV" ]; then
  echo "Creating universal2 build venv…"
  "$PY" -m venv "$VENV"
  "./$VENV/bin/pip" install --upgrade pip
  "./$VENV/bin/pip" install "PySide6<6.11" pyaaf2 pyavb openpyxl odfpy pyinstaller
fi

rm -rf build "dist/Timeline Reader.app" "dist/Timeline Reader"
TLR_TARGET_ARCH=universal2 "./$VENV/bin/pyinstaller" --noconfirm TimelineReader.spec

VER=$("./$VENV/bin/python" -c "import timeline_reader as t; print(t.__version__)")
ZIP="dist/TimelineReader-${VER}-macOS-universal.zip"
rm -f "$ZIP"
ditto -c -k --sequesterRsrc --keepParent "dist/Timeline Reader.app" "$ZIP"

echo
echo "Built universal2 bundle:"
lipo -archs "dist/Timeline Reader.app/Contents/MacOS/Timeline Reader"
echo "Packaged: $ZIP"

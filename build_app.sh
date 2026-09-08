#!/usr/bin/env bash
# Build a standalone "Timeline Reader.app" for macOS with PyInstaller.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install --upgrade pip
  ./.venv/bin/pip install -r requirements.txt
fi

./.venv/bin/pip install --quiet --upgrade pyinstaller
rm -rf build "dist/Timeline Reader.app"
./.venv/bin/pyinstaller --noconfirm TimelineReader.spec

echo
echo "Built: dist/Timeline Reader.app"
echo "Run with:  open 'dist/Timeline Reader.app'"

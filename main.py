"""Frozen-app / script entry point (absolute imports for PyInstaller)."""

from timeline_reader.app import main

if __name__ == "__main__":
    raise SystemExit(main())

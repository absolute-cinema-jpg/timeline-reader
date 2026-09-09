"""Locate bundled assets whether running from source or a frozen bundle."""

from __future__ import annotations

import os
import sys


def asset_path(name: str) -> str:
    """Return the absolute path to an asset, or "" if it does not exist."""
    base = getattr(
        sys,
        "_MEIPASS",
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    )
    path = os.path.join(base, "assets", name)
    return path if os.path.exists(path) else ""


def icon_path() -> str:
    """Return the absolute path to the app icon PNG, or "" if missing."""
    return asset_path("icon.png")

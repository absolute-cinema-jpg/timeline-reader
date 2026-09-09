"""Cross-session preferences, backed by QSettings.

Remembers small conveniences between runs: the folder you last opened a file
from, the folder you last exported to, the export format you chose, and the
caption frame rate. Uses the same ``QSettings`` store as the column
preferences, so everything lives in one place per OS user.

All accessors degrade gracefully — a missing or now-invalid value returns the
supplied default — and every call is cheap, so callers can read on demand.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QSettings

_ORG = "TimelineReader"
_APP = "TimelineReader"


def _store() -> QSettings:
    return QSettings(_ORG, _APP)


# --------------------------------------------------------------------------- #
# Directories
# --------------------------------------------------------------------------- #
def last_open_dir() -> str:
    """Folder of the last file the user opened (empty if unset/gone)."""
    d = _store().value("paths/last_open_dir", "", type=str)
    return d if d and os.path.isdir(d) else ""


def remember_open_path(path: str) -> None:
    _remember_dir("paths/last_open_dir", path)


def last_export_dir() -> str:
    d = _store().value("paths/last_export_dir", "", type=str)
    return d if d and os.path.isdir(d) else ""


def remember_export_path(path: str) -> None:
    _remember_dir("paths/last_export_dir", path)


def export_start_path(filename: str) -> str:
    """A suggested save path: last export folder + *filename*, or just the name."""
    d = last_export_dir()
    return os.path.join(d, filename) if d else filename


def _remember_dir(key: str, path: str) -> None:
    if not path:
        return
    directory = os.path.dirname(os.path.abspath(path))
    if os.path.isdir(directory):
        _store().setValue(key, directory)


# --------------------------------------------------------------------------- #
# Export format (stored by stable kind, not combo index)
# --------------------------------------------------------------------------- #
def export_format_kind(default: str = "csv") -> str:
    return _store().value("export/format_kind", default, type=str)


def set_export_format_kind(kind: str) -> None:
    _store().setValue("export/format_kind", kind)


# --------------------------------------------------------------------------- #
# Caption frame rate
# --------------------------------------------------------------------------- #
def caption_fps_index(default: int = 2) -> int:
    try:
        return int(_store().value("captions/fps_index", default))
    except (TypeError, ValueError):
        return default


def set_caption_fps_index(index: int) -> None:
    _store().setValue("captions/fps_index", int(index))

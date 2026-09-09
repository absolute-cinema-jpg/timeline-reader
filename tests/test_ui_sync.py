"""Cross-tab file sync: choosing a timeline file loads it in every timeline tab.

Run with:  QT_QPA_PLATFORM=offscreen ./.venv/bin/python tests/test_ui_sync.py
(or via pytest, which sets the offscreen platform below).
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

from timeline_reader.ui.main_window import MainWindow  # noqa: E402
from timeline_reader.ui.theme import apply_theme  # noqa: E402

_app = QApplication.instance() or QApplication([])
apply_theme(_app)


def _window_with_stubbed_loading():
    """A MainWindow whose tabs record _on_file calls instead of parsing files."""
    win = MainWindow()
    calls: list[tuple[str, str]] = []
    for name, tab in (
        ("opticals", win.opticals),
        ("cliplist", win.cliplist),
        ("markers", win.markers),
    ):
        def stub(path, _name=name, _tab=tab):
            _tab._path = path
            calls.append((_name, path))
        tab._on_file = stub
    return win, calls


def test_choosing_file_mirrors_to_all_timeline_tabs():
    win, calls = _window_with_stubbed_loading()
    win.opticals.drop.fileSelected.emit("/dir/THR.avb")
    _app.processEvents()
    assert set(calls) == {
        ("opticals", "/dir/THR.avb"),
        ("cliplist", "/dir/THR.avb"),
        ("markers", "/dir/THR.avb"),
    }
    assert win.cliplist._path == "/dir/THR.avb"
    assert win.markers._path == "/dir/THR.avb"


def test_already_loaded_tab_is_not_reloaded():
    win, calls = _window_with_stubbed_loading()
    win.cliplist._path = "/dir/THR.avb"  # already showing this file
    win.opticals.drop.fileSelected.emit("/dir/THR.avb")
    _app.processEvents()
    # opticals loads itself; markers is mirrored; cliplist is skipped.
    assert ("cliplist", "/dir/THR.avb") not in calls
    assert ("markers", "/dir/THR.avb") in calls


def test_clearing_does_not_propagate():
    win, calls = _window_with_stubbed_loading()
    win.cliplist.drop.fileSelected.emit("")  # a "Clear"
    _app.processEvents()
    # Only cliplist's own handler runs; nothing is mirrored to the others.
    assert calls == [("cliplist", "")]


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok  {_name}")
    print("all tests passed")

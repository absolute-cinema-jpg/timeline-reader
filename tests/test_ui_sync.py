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
        ("tagfinder", win.tagfinder),
        ("music", win.music),
        ("captions", win.captions),
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
        ("tagfinder", "/dir/THR.avb"),
        ("music", "/dir/THR.avb"),
        ("captions", "/dir/THR.avb"),
    }
    assert win.cliplist._path == "/dir/THR.avb"
    assert win.music._path == "/dir/THR.avb"
    assert win.captions._path == "/dir/THR.avb"


def test_already_loaded_tab_is_not_reloaded():
    win, calls = _window_with_stubbed_loading()
    win.cliplist._path = "/dir/THR.avb"  # already showing this file
    win.opticals.drop.fileSelected.emit("/dir/THR.avb")
    _app.processEvents()
    # opticals loads itself; music is mirrored; cliplist is skipped.
    assert ("cliplist", "/dir/THR.avb") not in calls
    assert ("music", "/dir/THR.avb") in calls


def test_clearing_does_not_propagate():
    win, calls = _window_with_stubbed_loading()
    win.cliplist.drop.fileSelected.emit("")  # a "Clear"
    _app.processEvents()
    # Only cliplist's own handler runs; nothing is mirrored to the others.
    assert calls == [("cliplist", "")]


def _window_with_stubbed_sequence_loads():
    """A MainWindow whose tabs record sequence loads instead of parsing."""
    win = MainWindow()
    loads: list[tuple[str, str, int | None]] = []
    for name, tab in (
        ("opticals", win.opticals),
        ("cliplist", win.cliplist),
        ("tagfinder", win.tagfinder),
        ("music", win.music),
    ):
        def stub(path, key, _name=name, _tab=tab):
            _tab._seq_key = key
            loads.append((_name, path, key))
        tab._load = stub
        tab._path = "/dir/THR.avb"

    def caption_stub(_tab=win.captions):
        loads.append(("captions", _tab._path, _tab._seq_key))
    win.captions._reconvert = caption_stub
    win.captions._path = "/dir/THR.avb"
    return win, loads


def test_picking_a_sequence_follows_into_every_tab():
    win, loads = _window_with_stubbed_sequence_loads()
    # Populate cliplist's picker as a parsed 3-sequence bin would, then pick #2.
    win.cliplist._suppress_switch = True
    win.cliplist.seq_combo.addItems(["A", "B", "C"])
    win.cliplist.seq_combo.setCurrentIndex(0)
    win.cliplist._suppress_switch = False
    win.cliplist.seq_combo.setCurrentIndex(2)
    _app.processEvents()
    assert set(loads) == {
        ("cliplist", "/dir/THR.avb", 2),
        ("opticals", "/dir/THR.avb", 2),
        ("tagfinder", "/dir/THR.avb", 2),
        ("music", "/dir/THR.avb", 2),
        ("captions", "/dir/THR.avb", 2),
    }
    assert win.music._seq_key == 2 and win.captions._seq_key == 2


def test_tab_already_on_that_sequence_is_not_reloaded():
    win, loads = _window_with_stubbed_sequence_loads()
    win.music._seq_key = 1  # already showing sequence 1 of this file
    win.opticals.sequenceChanged.emit("/dir/THR.avb", 1)
    _app.processEvents()
    assert ("music", "/dir/THR.avb", 1) not in loads
    assert ("cliplist", "/dir/THR.avb", 1) in loads
    assert ("opticals", "/dir/THR.avb", 1) not in loads  # the origin loads itself


def test_fps_preset_matches_exact_rate_not_rounded():
    """A 24 fps sequence must map to '24', not '23.976' — rounding collapses the
    two (both round to 24) and, since 23.976 is listed first, would mislabel every
    24 fps bin. Same trap for 29.97 vs 30 and 59.94 vs 60."""
    from timeline_reader.ui.captions_tab import _FPS_CHOICES, _fps_preset_index

    def label(fps, drop=False):
        i = _fps_preset_index(fps, drop)
        return _FPS_CHOICES[i][0] if i is not None else None

    assert label(24.0) == "24"
    assert label(24000 / 1001) == "23.976"
    assert label(25.0) == "25 (PAL)"
    assert label(30.0) == "30"
    assert label(30000 / 1001) == "29.97 NDF"
    assert label(30000 / 1001, drop=True) == "29.97 DF"
    assert label(60.0) == "60"
    assert label(60000 / 1001) == "59.94"


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok  {_name}")
    print("all tests passed")

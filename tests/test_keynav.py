"""Keyboard navigation: ⇧← ⇧→ change tab, ⇧↑ ⇧↓ change sequence, ⇧Enter opens
the file picker, Enter exports. Plain arrows stay with the table.

Run with:  QT_QPA_PLATFORM=offscreen ./.venv/bin/python tests/test_keynav.py
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from timeline_reader.ui.main_window import MainWindow  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _window():
    win = MainWindow()
    win.show()
    win.activateWindow()
    _app.processEvents()
    win.keynav._applies = lambda: True  # offscreen: no real active window
    return win


def _key(win, key, mods=Qt.ShiftModifier):
    QTest.keyClick(win.tabs.currentWidget(), key, mods)
    _app.processEvents()


def test_shift_left_right_step_through_tabs_in_order():
    win = _window()
    assert win.tabs.currentWidget() is win.cliplist
    _key(win, Qt.Key_Right)
    assert win.tabs.currentWidget() is win.opticals
    _key(win, Qt.Key_Right)
    assert win.tabs.currentWidget() is win.tagfinder
    _key(win, Qt.Key_Left)
    assert win.tabs.currentWidget() is win.opticals
    _key(win, Qt.Key_Left)
    _key(win, Qt.Key_Left)  # wraps from the first tab round to the last
    assert win.tabs.currentWidget() is win.captions


def test_plain_arrows_are_left_to_the_table():
    win = _window()
    win.cliplist.table.setFocus()
    _key(win, Qt.Key_Right, Qt.NoModifier)
    _key(win, Qt.Key_Down, Qt.NoModifier)
    assert win.tabs.currentWidget() is win.cliplist
    _key(win, Qt.Key_Right, Qt.ControlModifier)  # other modifiers: not ours either
    assert win.tabs.currentWidget() is win.cliplist


def test_shift_enter_browses_and_enter_exports():
    win = _window()
    calls: list[str] = []
    win.cliplist.drop._browse = lambda: calls.append("browse")
    win.cliplist._export = lambda: calls.append("export")
    win.cliplist.export_btn.clicked.disconnect()
    win.cliplist.export_btn.clicked.connect(win.cliplist._export)

    _key(win, Qt.Key_Return, Qt.NoModifier)  # nothing loaded: Export is disabled
    assert calls == []
    _key(win, Qt.Key_Return)                 # ⇧Enter: Browse…
    assert calls == ["browse"]

    win.cliplist._path = "/dir/THR.avb"
    win.cliplist.export_btn.setEnabled(True)
    _key(win, Qt.Key_Return, Qt.NoModifier)
    assert calls == ["browse", "export"]
    _key(win, Qt.Key_Return)                 # ⇧Enter with a file loaded: Replace…
    assert calls == ["browse", "export", "browse"]

    win.cliplist.export_btn.setEnabled(False)  # e.g. still loading: nothing happens
    _key(win, Qt.Key_Return, Qt.NoModifier)
    assert calls == ["browse", "export", "browse"]


def test_shift_up_down_cycle_sequences_only_with_a_multi_sequence_file():
    win = _window()
    tab = win.cliplist
    loads: list[int] = []
    tab._load = lambda path, key: loads.append(key)
    for other in win._timeline_tabs:  # siblings would follow with real loads
        other.set_sequence = lambda path, key: None

    _key(win, Qt.Key_Down)  # nothing loaded: no-op
    assert loads == []

    tab._path = "/dir/THR.avb"
    tab._suppress_switch = True
    tab.seq_combo.addItems(["A", "B", "C"])
    tab.seq_combo.setCurrentIndex(0)
    tab._suppress_switch = False
    tab.seq_row.show()

    _key(win, Qt.Key_Down)
    _key(win, Qt.Key_Down)
    _key(win, Qt.Key_Down)  # wraps back to the first
    _key(win, Qt.Key_Up)
    assert loads == [1, 2, 0, 2]
    assert tab.seq_combo.currentIndex() == 2

    tab.seq_row.hide()      # a single-sequence file hides the picker
    _key(win, Qt.Key_Down)
    assert loads == [1, 2, 0, 2]


def test_text_fields_keep_their_own_keys():
    win = _window()
    del win.keynav._applies  # use the real check, with the search field focused
    win.tabs.setCurrentWidget(win.tagfinder)
    win.tagfinder._search.setFocus()
    _app.processEvents()
    assert _app.focusWidget() is win.tagfinder._search
    QTest.keyClick(win.tagfinder._search, Qt.Key_Right, Qt.ShiftModifier)  # selects text
    _app.processEvents()
    assert win.tabs.currentWidget() is win.tagfinder


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok  {_name}")
    print("all tests passed")

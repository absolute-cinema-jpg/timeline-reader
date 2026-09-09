"""⌘W closes the window (and thus the single-window app).

Run with:  QT_QPA_PLATFORM=offscreen ./.venv/bin/python tests/test_shortcuts.py
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from timeline_reader.app import install_shortcuts  # noqa: E402
from timeline_reader.ui.main_window import MainWindow  # noqa: E402

_app = QApplication.instance() or QApplication([])


def test_close_shortcut_is_cmd_w():
    win = MainWindow()
    sc = install_shortcuts(win)
    # 'Ctrl+W' == ⌘W on macOS (Qt maps Ctrl to the Command key there).
    assert sc.key() == QKeySequence("Ctrl+W")
    assert sc.key().toString().upper() == "CTRL+W"


def test_close_shortcut_closes_window():
    win = MainWindow()
    install_shortcuts(win)
    win.show()
    _app.processEvents()
    assert win.isVisible()
    win._close_shortcut = None  # not needed here; sc parented to win
    # Trigger the shortcut's effect.
    install_shortcuts(win).activated.emit()
    _app.processEvents()
    assert not win.isVisible()


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok  {_name}")
    print("all tests passed")

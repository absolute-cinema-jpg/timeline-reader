"""Keyboard navigation for the main window.

    ←  →       previous / next tab
    ↑  ↓       previous / next sequence in the loaded bin (wraps)
    Enter      no file loaded: open the file picker; file loaded: Export

One application-wide event filter, so the keys work wherever focus happens to
be — except in widgets that need the same keys for themselves: text fields
(the Tag Finder search, the SRT preview), spin boxes and combo boxes keep
their arrows and Enter. Modified keys (⌘←, ⌥→ …) are left alone, as is
anything typed while a popup or dialog is up.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
)

# Widgets whose own handling of arrows / Enter must not be overridden.
_TEXT_ENTRY = (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox)


class KeyNav(QObject):
    def __init__(self, win):
        super().__init__(win)
        self._win = win
        QApplication.instance().installEventFilter(self)

    # ---- filter ------------------------------------------------------------
    def eventFilter(self, obj, event):
        if event.type() != QEvent.KeyPress or not self._applies():
            return False
        if event.modifiers() & ~Qt.KeypadModifier:
            return False
        key = event.key()
        if key == Qt.Key_Right:
            self.step_tab(+1)
        elif key == Qt.Key_Left:
            self.step_tab(-1)
        elif key == Qt.Key_Down:
            self.step_sequence(+1)
        elif key == Qt.Key_Up:
            self.step_sequence(-1)
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            self.activate()
        else:
            return False
        return True

    def _applies(self) -> bool:
        app = QApplication.instance()
        if app.activePopupWidget() is not None or app.activeModalWidget() is not None:
            return False
        if app.activeWindow() is not self._win:
            return False
        focus = app.focusWidget()
        return not isinstance(focus, _TEXT_ENTRY)

    # ---- actions -----------------------------------------------------------
    def step_tab(self, delta: int) -> None:
        tabs = self._win.tabs
        n = tabs.count()
        if n:
            tabs.setCurrentIndex((tabs.currentIndex() + delta) % n)

    def step_sequence(self, delta: int) -> None:
        """Cycle the current tab's sequence picker; the tab loads the sequence
        and mirrors the choice into its siblings as if picked with the mouse."""
        tab = self._win.tabs.currentWidget()
        combo = getattr(tab, "seq_combo", None)
        if combo is None or not getattr(tab, "_path", ""):
            return
        # The picker is hidden (and may hold a stale list) for a single-sequence file.
        if tab.seq_row.isHidden() or combo.count() < 2:
            return
        combo.setCurrentIndex((combo.currentIndex() + delta) % combo.count())

    def activate(self) -> None:
        """Enter: pick a file if none is loaded, otherwise export."""
        tab = self._win.tabs.currentWidget()
        if tab is None:
            return
        if not getattr(tab, "_path", ""):
            tab.drop._browse()
        elif tab.export_btn.isEnabled():
            tab.export_btn.click()

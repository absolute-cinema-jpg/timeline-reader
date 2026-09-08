"""Reusable UI widgets: drag-and-drop file zone and a report table."""

from __future__ import annotations

import os

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from . import theme

# Columns whose values are timecodes/durations -> render monospaced.
_MONO_HINTS = ("in", "out", "duration", "#")


class DropZone(QFrame):
    """A dashed drop target that also offers a Browse button."""

    fileSelected = Signal(str)

    def __init__(self, title: str, subtitle: str, extensions: list[str], parent=None):
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setProperty("dragActive", False)
        self.setProperty("loaded", False)
        self._extensions = [e.lower() for e in extensions]
        self._default_title = title
        self._default_sub = subtitle

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 22, 20, 22)
        lay.setSpacing(6)
        lay.setAlignment(Qt.AlignCenter)

        self.icon = QLabel("⬇")
        self.icon.setObjectName("DropIcon")
        self.icon.setAlignment(Qt.AlignCenter)
        self.title = QLabel(title)
        self.title.setObjectName("DropTitle")
        self.title.setAlignment(Qt.AlignCenter)
        self.sub = QLabel(subtitle)
        self.sub.setObjectName("DropSub")
        self.sub.setAlignment(Qt.AlignCenter)

        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignCenter)
        self.browse = QPushButton("Browse…")
        self.browse.clicked.connect(self._browse)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear)
        self.clear_btn.hide()
        btn_row.addWidget(self.browse)
        btn_row.addWidget(self.clear_btn)

        lay.addWidget(self.icon)
        lay.addWidget(self.title)
        lay.addWidget(self.sub)
        lay.addSpacing(4)
        lay.addLayout(btn_row)

    # ---- drag & drop ----
    def _accepts(self, path: str) -> bool:
        return any(path.lower().endswith(e) for e in self._extensions)

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if urls and self._accepts(urls[0].toLocalFile()):
            event.acceptProposedAction()
            self._set_drag(True)

    def dragLeaveEvent(self, event):
        self._set_drag(False)

    def dropEvent(self, event):
        self._set_drag(False)
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if self._accepts(path):
                self.fileSelected.emit(path)
                return

    def _set_drag(self, active: bool):
        self.setProperty("dragActive", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def _browse(self):
        pattern = " ".join(f"*{e}" for e in self._extensions)
        path, _ = QFileDialog.getOpenFileName(
            self, "Select file", "", f"Supported files ({pattern});;All files (*)"
        )
        if path:
            self.fileSelected.emit(path)

    # ---- state ----
    def show_loaded(self, path: str, meta: str = ""):
        self.icon.setText("🎬")
        self.title.setText(os.path.basename(path))
        self.sub.setText(meta or path)
        self.clear_btn.show()
        self.browse.setText("Replace…")
        self.setProperty("loaded", True)
        self.style().unpolish(self)
        self.style().polish(self)

    def clear(self):
        self.icon.setText("⬇")
        self.title.setText(self._default_title)
        self.sub.setText(self._default_sub)
        self.clear_btn.hide()
        self.browse.setText("Browse…")
        self.setProperty("loaded", False)
        self.style().unpolish(self)
        self.style().polish(self)
        self.fileSelected.emit("")


class TableModel(QAbstractTableModel):
    """Simple string-grid model with monospaced timecode columns."""

    def __init__(self, headers=None, rows=None, parent=None):
        super().__init__(parent)
        self._headers = headers or []
        self._rows = rows or []
        self._mono_cols = {
            i for i, h in enumerate(self._headers)
            if any(hint in h.lower() for hint in _MONO_HINTS)
        }
        self._effect_col = self._find_col("effect")
        self._mono = QFont("SF Mono")
        self._mono.setStyleHint(QFont.Monospace)
        self._mono.setPointSize(12)

    def _find_col(self, name: str):
        for i, h in enumerate(self._headers):
            if h.lower() == name:
                return i
        return -1

    def set_data(self, headers, rows):
        self.beginResetModel()
        self._headers = headers
        self._rows = rows
        self._mono_cols = {
            i for i, h in enumerate(headers)
            if any(hint in h.lower() for hint in _MONO_HINTS)
        }
        self._effect_col = self._find_col("effect")
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._headers)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        value = self._rows[row][col] if col < len(self._rows[row]) else ""
        if role == Qt.DisplayRole:
            return value
        if role == Qt.FontRole and col in self._mono_cols:
            return self._mono
        if role == Qt.ForegroundRole and col == self._effect_col and value:
            return QColor(theme.AMBER)
        if role == Qt.TextAlignmentRole and col in self._mono_cols:
            return int(Qt.AlignVCenter | Qt.AlignLeft)
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self._headers[section]
        return str(section + 1)

    @property
    def rows(self):
        return self._rows

    @property
    def headers(self):
        return self._headers


class ReportTable(QTableView):
    """A read-only, sortable, nicely-defaulted table view."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = TableModel()
        self.setModel(self._model)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setShowGrid(False)
        self.setSortingEnabled(False)
        self.setWordWrap(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(28)
        self.horizontalHeader().setHighlightSections(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.horizontalHeader().setSectionsMovable(True)  # drag headers to reorder

    def set_data(self, headers, rows):
        self._model.set_data(headers, rows)
        self._reset_visual_order()
        self.resizeColumnsToContents()
        header = self.horizontalHeader()
        for c in range(self._model.columnCount()):
            if header.sectionSize(c) > 320:
                header.resizeSection(c, 320)

    def _reset_visual_order(self):
        """Restore visual==logical order. Qt keeps a header's moved-section map
        across model resets, so after we rebuild data in a new order we must
        clear it. Signals are blocked so this doesn't re-fire ``sectionMoved``."""
        header = self.horizontalHeader()
        header.blockSignals(True)
        for logical in range(self._model.columnCount()):
            visual = header.visualIndex(logical)
            if visual != logical:
                header.moveSection(visual, logical)
        header.blockSignals(False)

    @property
    def model_(self):
        return self._model


def make_card(parent=None) -> QFrame:
    card = QFrame(parent)
    card.setObjectName("Card")
    return card


def section_label(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setObjectName("SectionLabel")
    return lbl

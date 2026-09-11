"""Reusable UI widgets: drag-and-drop file zone and a report table."""

from __future__ import annotations

import os

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
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
# Identity columns tinted apart from the rest (matched on header label).
_IDENTITY_LABELS = {"#", "clip name"}


class LoadWorkers(QObject):
    """Owns a tab's background load threads until each has finished.

    A ``QThread`` must never be garbage-collected while it is still running —
    Qt aborts the whole app ("QThread: Destroyed while thread is still
    running"). Tabs used to keep a single ``_worker`` reference and overwrite it
    on every load, so a second load issued while a slow parse was still going
    (a 500 MB bin on an older Mac, then a sequence pick or a second drop)
    orphaned the running thread, which then destroyed itself as it finished.

    Every started worker is held here until its ``finished`` signal. Only the
    most recently started one is *current*: a result or error from a superseded
    load is dropped, so a late-arriving old parse can't overwrite a newer
    choice. Slots are bound methods of this object (which lives on the tab's
    thread), so callbacks always run on the UI thread.
    """

    def __init__(self, on_done, on_failed, parent: QObject | None = None):
        super().__init__(parent)
        self._on_done = on_done
        self._on_failed = on_failed
        self._live: list = []
        self._current = None

    def start(self, worker) -> None:
        """Start ``worker`` (a QThread with ``done``/``failed`` signals) and
        make it the current load."""
        self._live.append(worker)
        self._current = worker
        worker.done.connect(self._done)
        worker.failed.connect(self._failed)
        worker.finished.connect(self._finished)
        worker.start()

    @property
    def busy(self) -> bool:
        return self._current is not None

    def _done(self, result):
        if self.sender() is self._current:
            self._on_done(result)

    def _failed(self, message: str):
        if self.sender() is self._current:
            self._on_failed(message)

    def _finished(self):
        worker = self.sender()
        if worker is self._current:
            self._current = None
        if worker in self._live:
            self._live.remove(worker)


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
                self._emit(path)
                return

    def _emit(self, path: str) -> None:
        """Emit a chosen path, remembering its folder for next time."""
        from .. import settings
        settings.remember_open_path(path)
        self.fileSelected.emit(path)

    def _set_drag(self, active: bool):
        self.setProperty("dragActive", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def _browse(self):
        from .. import settings
        pattern = " ".join(f"*{e}" for e in self._extensions)
        path, _ = QFileDialog.getOpenFileName(
            self, "Select file", settings.last_open_dir(),
            f"Supported files ({pattern});;All files (*)"
        )
        if path:
            self._emit(path)

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
        self._id_cols = self._identity_cols(self._headers)
        self._mono = QFont("SF Mono")
        self._mono.setStyleHint(QFont.Monospace)
        self._mono.setPointSize(12)

    @staticmethod
    def _identity_cols(headers) -> set[int]:
        return {i for i, h in enumerate(headers) if h.lower() in _IDENTITY_LABELS}

    def set_data(self, headers, rows):
        self.beginResetModel()
        self._headers = headers
        self._rows = rows
        self._mono_cols = {
            i for i, h in enumerate(headers)
            if any(hint in h.lower() for hint in _MONO_HINTS)
        }
        self._id_cols = self._identity_cols(headers)
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
        if role == Qt.ForegroundRole:
            if col in self._id_cols:
                return QColor(theme.IDENTITY)
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


class _SortProxy(QSortFilterProxyModel):
    """Sort proxy that orders numeric columns (e.g. ``#``) numerically and
    everything else as case-insensitive text."""

    def lessThan(self, left, right):
        lv = self.sourceModel().data(left, Qt.DisplayRole) or ""
        rv = self.sourceModel().data(right, Qt.DisplayRole) or ""
        try:
            return float(lv) < float(rv)
        except (TypeError, ValueError):
            return lv.casefold() < rv.casefold()


class ReportTable(QTableView):
    """A read-only, sortable, nicely-defaulted table view."""

    #: Emitted when Delete/Backspace is pressed with rows selected.
    deleteKeyPressed = Signal()

    #: Column whose ascending order is the default when data (re)loads.
    _DEFAULT_SORT = "#"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = TableModel()
        self._proxy = _SortProxy(self)
        self._proxy.setSourceModel(self._model)
        self.setModel(self._proxy)
        self._sort_label = self._DEFAULT_SORT
        self._sort_order = Qt.AscendingOrder
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setShowGrid(False)
        self.setSortingEnabled(True)  # click a header to sort by that column
        self.setWordWrap(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(28)
        self.horizontalHeader().setHighlightSections(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.horizontalHeader().setSectionsMovable(True)  # drag headers to reorder
        self.horizontalHeader().sortIndicatorChanged.connect(self._remember_sort)

    def _remember_sort(self, section, order):
        """Track the user's chosen sort by column *label* so it survives the
        model resets that happen when columns are reordered or reloaded."""
        headers = self._model.headers
        if 0 <= section < len(headers):
            self._sort_label = headers[section]
            self._sort_order = order

    def set_data(self, headers, rows):
        self._model.set_data(headers, rows)
        self._reset_visual_order()
        self._apply_sort()
        self.resizeColumnsToContents()
        header = self.horizontalHeader()
        for c in range(self._model.columnCount()):
            if header.sectionSize(c) > 320:
                header.resizeSection(c, 320)

    def _apply_sort(self):
        """Re-sort by the remembered column, falling back to the default one."""
        headers = self._model.headers
        for label in (self._sort_label, self._DEFAULT_SORT):
            if label in headers:
                self.sortByColumn(headers.index(label), self._sort_order)
                return
        self._proxy.sort(-1)  # no matching column: leave rows in source order

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

    def keyPressEvent(self, event):
        # Escape clears the row selection (back to "export everything").
        if event.key() == Qt.Key_Escape and self.selectionModel().hasSelection():
            self.clearSelection()
            event.accept()
            return
        # Delete / Backspace removes the selected rows (the tab does the work).
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.selectionModel().hasSelection():
            self.deleteKeyPressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def selected_rows(self) -> list[int]:
        """Source-row indices of the currently selected rows, in the order they
        appear on screen. Empty when nothing is selected."""
        sm = self.selectionModel()
        if sm is None:
            return []
        idxs = sorted(sm.selectedRows(), key=lambda ix: ix.row())
        return [self._proxy.mapToSource(ix).row() for ix in idxs]

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

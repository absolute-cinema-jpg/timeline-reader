"""Base tab for timeline-driven reports (Opticals list, Clip list).

Loads a timeline file (bin / EDL / AAF / tab-delimited) off the UI thread,
builds a table via an injected report function, and exports to CSV/TSV.
"""

from __future__ import annotations

import os
from typing import Callable

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..columns import ColumnSelection, Report
from .. import settings
from ..exporters import (
    export_table,
    format_at,
    format_labels,
    index_of_kind,
    kind_at,
    rows_to_delimited,
)
from ..models import Timeline
from ..parsers import ParseError, parse_timeline
from .column_dialog import ColumnDialog
from .widgets import DropZone, ReportTable, make_card, section_label

TIMELINE_EXTS = [".avb", ".edl", ".aaf", ".txt", ".tsv", ".tab"]


class _ParseWorker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, path: str, key: int | None = None):
        super().__init__()
        self._path = path
        self._key = key

    def run(self):
        try:
            tl = parse_timeline(self._path, self._key)
            self.done.emit(tl)
        except ParseError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"Unexpected error: {exc}")


class TimelineReportTab(QWidget):
    status = Signal(str)

    def __init__(
        self,
        report: Report,
        drop_title: str,
        drop_sub: str,
        export_basename: str,
        empty_hint: str,
        parent=None,
    ):
        super().__init__(parent)
        self._report = report
        self._selection = ColumnSelection(report.key).load()
        self._export_basename = export_basename
        self._empty_hint = empty_hint
        self._drop_title_text = drop_title
        self._drop_sub_text = drop_sub
        self._timeline: Timeline | None = None
        self._headers: list[str] = []
        self._rows: list[list[str]] = []
        self._worker: _ParseWorker | None = None
        self._path: str = ""
        self._suppress_switch = False
        self._col_ids: list[str] = []
        self._build()

    # ---- layout -----------------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(14)

        top = QHBoxLayout()
        top.setSpacing(14)

        self.drop = DropZone(self._drop_title_text, self._drop_sub_text, TIMELINE_EXTS)
        self.drop.fileSelected.connect(self._on_file)
        self.drop.setMinimumWidth(360)
        self.drop.setMaximumWidth(460)
        top.addWidget(self.drop)

        top.addWidget(self._info_card(), 1)
        root.addLayout(top)

        self.table = ReportTable()
        self.table.setToolTip(
            "Exports every row by default. Select rows to export just those "
            "(⌘/Shift-click for more); Esc or “Clear selection” goes back to all."
        )
        self.table.horizontalHeader().sectionMoved.connect(self._on_section_moved)
        root.addWidget(self.table, 1)

        root.addLayout(self._action_bar())
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._update_actions()

    def _info_card(self):
        card = make_card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(8)

        head = QHBoxLayout()
        head.addWidget(section_label("Timeline"))
        head.addStretch(1)
        self.format_badge = QLabel("")
        self.format_badge.setObjectName("FormatBadge")
        self.format_badge.hide()
        head.addWidget(self.format_badge)
        lay.addLayout(head)

        self.seq_name = QLabel("No file loaded")
        self.seq_name.setObjectName("DropTitle")
        lay.addWidget(self.seq_name)

        # Sequence picker — shown only when a bin/AAF holds more than one.
        self.seq_row = QWidget()
        seq_lay = QHBoxLayout(self.seq_row)
        seq_lay.setContentsMargins(0, 0, 0, 0)
        seq_lay.setSpacing(8)
        seq_lay.addWidget(QLabel("Sequence:"))
        self.seq_combo = QComboBox()
        self.seq_combo.setMinimumWidth(240)
        self.seq_combo.currentIndexChanged.connect(self._switch_sequence)
        seq_lay.addWidget(self.seq_combo, 1)
        seq_lay.addStretch(0)
        self.seq_row.hide()
        lay.addWidget(self.seq_row)

        stats = QHBoxLayout()
        stats.setSpacing(28)
        self.stat_clips = self._stat("—", "CLIPS")
        self.stat_rows = self._stat("—", self._rows_stat_label())
        self.stat_fps = self._stat("—", "FPS")
        stats.addLayout(self.stat_clips[0])
        stats.addLayout(self.stat_rows[0])
        stats.addLayout(self.stat_fps[0])
        stats.addStretch(1)
        lay.addLayout(stats)

        self.warn = QLabel("")
        self.warn.setObjectName("WarnLabel")
        self.warn.setWordWrap(True)
        self.warn.hide()
        lay.addWidget(self.warn)
        lay.addStretch(1)
        return card

    def _rows_stat_label(self) -> str:
        return "ROWS"

    def _stat(self, value: str, label: str):
        box = QVBoxLayout()
        box.setSpacing(0)
        v = QLabel(value)
        v.setObjectName("StatBig")
        l = QLabel(label)
        l.setObjectName("StatLabel")
        box.addWidget(v)
        box.addWidget(l)
        return box, v, l

    def _action_bar(self):
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.row_count = QLabel(self._empty_hint)
        self.row_count.setObjectName("Hint")
        bar.addWidget(self.row_count)
        bar.addStretch(1)

        self.clear_sel_btn = QPushButton("Clear selection")
        self.clear_sel_btn.clicked.connect(self.table.clearSelection)
        self.clear_sel_btn.hide()  # only shown while rows are selected
        bar.addWidget(self.clear_sel_btn)

        self.columns_btn = QPushButton("Columns…")
        self.columns_btn.clicked.connect(self._choose_columns)
        bar.addWidget(self.columns_btn)

        bar.addWidget(QLabel("Format:"))
        self.fmt = QComboBox()
        self.fmt.addItems(format_labels())
        self.fmt.setCurrentIndex(index_of_kind(settings.export_format_kind()))
        self.fmt.currentIndexChanged.connect(
            lambda i: settings.set_export_format_kind(kind_at(i))
        )
        bar.addWidget(self.fmt)

        self.copy_btn = QPushButton("Copy")
        self.copy_btn.clicked.connect(self._copy)
        bar.addWidget(self.copy_btn)

        self.export_btn = QPushButton("Export…")
        self.export_btn.setObjectName("Primary")
        self.export_btn.clicked.connect(self._export)
        bar.addWidget(self.export_btn)
        return bar

    # ---- loading ----------------------------------------------------------
    def _on_file(self, path: str):
        if not path:
            self._reset()
            return
        self._path = path
        self._load(path, key=None)

    def _switch_sequence(self, index: int):
        if self._suppress_switch or not self._path or index < 0:
            return
        self.status.emit("Switching sequence…")
        self._load(self._path, key=index)

    def _load(self, path: str, key: int | None):
        self.status.emit(f"Reading {os.path.basename(path)}…")
        QGuiApplication.setOverrideCursor(Qt.BusyCursor)
        self.export_btn.setEnabled(False)
        self._worker = _ParseWorker(path, key)
        self._worker.done.connect(self._on_parsed)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(lambda: QGuiApplication.restoreOverrideCursor())
        self._worker.start()

    def _on_parsed(self, tl: Timeline):
        self._timeline = tl
        try:
            cols, self._rows = self._report.render(tl, self._selection)
        except Exception as exc:  # noqa: BLE001
            self._on_failed(f"Report build failed: {exc}")
            return
        self._col_ids = [c.id for c in cols]
        self._headers = [c.label for c in cols]
        self.table.set_data(self._headers, self._rows)
        meta = f"{tl.source_format} · {tl.fps:g} fps · {len(tl.clips)} clips"
        self.drop.show_loaded(tl.source_path, meta)
        self.format_badge.setText(tl.source_format)
        self.format_badge.show()
        self.seq_name.setText(tl.name or "(untitled sequence)")
        self._populate_sequences(tl)
        self.stat_clips[1].setText(str(len(tl.clips)))
        self.stat_rows[1].setText(str(len(self._rows)))
        self.stat_fps[1].setText(f"{tl.fps:g}")
        if tl.warnings:
            self.warn.setText("⚠ " + "  ".join(tl.warnings))
            self.warn.show()
        else:
            self.warn.hide()
        self.row_count.setText(f"{len(self._rows)} rows ready to export")
        self._update_actions()
        self.status.emit(
            f"Loaded {os.path.basename(tl.source_path)} — {len(self._rows)} rows"
        )

    def _populate_sequences(self, tl: Timeline):
        opts = tl.available_sequences
        if len(opts) <= 1:
            self.seq_row.hide()
            return
        self._suppress_switch = True
        self.seq_combo.clear()
        for opt in opts:
            label = opt.name if not opt.detail else f"{opt.name}   ({opt.detail})"
            self.seq_combo.addItem(label)
        current = tl.sequence_key if tl.sequence_key is not None else 0
        self.seq_combo.setCurrentIndex(current)
        self._suppress_switch = False
        self.seq_row.show()

    def _on_failed(self, message: str):
        QGuiApplication.restoreOverrideCursor()
        self.status.emit("Load failed")
        QMessageBox.warning(self, "Could not load file", message)
        self._update_actions()

    def _reset(self):
        self._timeline = None
        self._path = ""
        self._headers, self._rows = [], []
        self.table.set_data([], [])
        self.format_badge.hide()
        self.seq_row.hide()
        self.seq_name.setText("No file loaded")
        for _, v, _l in (self.stat_clips, self.stat_rows, self.stat_fps):
            v.setText("—")
        self.warn.hide()
        self.row_count.setText(self._empty_hint)
        self._update_actions()

    def _update_actions(self):
        has = bool(self._rows)
        self.export_btn.setEnabled(has)
        self.copy_btn.setEnabled(has)
        self.columns_btn.setEnabled(self._timeline is not None)
        self._on_selection_changed()

    def _on_selection_changed(self, *_):
        """Keep the export controls in sync with the row selection so it's always
        clear whether you'll export everything or just the highlighted rows."""
        n = len(self.table.selected_rows()) if self._rows else 0
        if n:
            self.export_btn.setText(f"Export {n} selected…")
            self.clear_sel_btn.show()
        else:
            self.export_btn.setText("Export all…")
            self.clear_sel_btn.hide()

    # ---- columns ----------------------------------------------------------
    def _choose_columns(self):
        if self._timeline is None:
            return
        cols = self._report.all_columns(self._timeline)
        dlg = ColumnDialog(cols, self._selection, self)
        if dlg.exec():
            self._rebuild_rows()

    def _rebuild_rows(self):
        if self._timeline is None:
            return
        cols, self._rows = self._report.render(self._timeline, self._selection)
        self._col_ids = [c.id for c in cols]
        self._headers = [c.label for c in cols]
        self.table.set_data(self._headers, self._rows)
        self.stat_rows[1].setText(str(len(self._rows)))
        self.row_count.setText(f"{len(self._rows)} rows · {len(self._headers)} columns")
        self._update_actions()

    def _on_section_moved(self, logical: int, old_visual: int, new_visual: int):
        """User dragged a table header: persist the new order and rebuild so the
        model, export and saved order all agree (the header resets to identity)."""
        if not self._col_ids or self._timeline is None:
            return
        header = self.table.horizontalHeader()
        n = len(self._col_ids)
        visible_order = [self._col_ids[header.logicalIndex(v)] for v in range(n)]
        # Keep any currently-hidden columns' saved positions after the visible ones.
        hidden = [cid for cid in self._selection.order if cid not in visible_order]
        self._selection.set_order(visible_order + hidden)
        self._selection.save()
        self._rebuild_rows()
        self.status.emit("Columns reordered")

    # ---- output -----------------------------------------------------------
    def _base_name(self) -> str:
        base = self._timeline.name if self._timeline else self._export_basename
        base = "".join(c if c.isalnum() or c in "-_ " else "_" for c in base).strip()
        return base or self._export_basename

    def _suggested_name(self):
        # Default filename is just the chosen sequence's name.
        _label, ext, _filt, _kind = format_at(self.fmt.currentIndex())
        return f"{self._base_name()}{ext}"

    def _selected_or_all_rows(self):
        """Rows to output: just the selected ones (in on-screen order) if the
        user has a selection, otherwise the whole report."""
        sel = self.table.selected_rows()
        if sel:
            return [self._rows[i] for i in sel], True
        return self._rows, False

    def _export(self):
        if not self._rows:
            return
        rows, is_selection = self._selected_or_all_rows()
        _label, ext, filt, kind = format_at(self.fmt.currentIndex())
        start = settings.export_start_path(self._suggested_name())
        path, _ = QFileDialog.getSaveFileName(self, "Export report", start, filt)
        if not path:
            return
        if not path.lower().endswith(ext):
            path += ext
        try:
            export_table(path, self._headers, rows, kind, sheet_name=self._base_name())
        except (OSError, RuntimeError) as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        settings.remember_export_path(path)
        what = f"{len(rows)} selected rows" if is_selection else f"{len(rows)} rows"
        self.status.emit(f"Exported {what} → {path}")
        QMessageBox.information(
            self, "Export complete",
            f"Wrote {what} to:\n{path}",
        )

    def _copy(self):
        if not self._rows:
            return
        rows, is_selection = self._selected_or_all_rows()
        text = rows_to_delimited(self._headers, rows, "\t")
        QApplication.clipboard().setText(text)
        what = f"{len(rows)} selected rows" if is_selection else "table"
        self.status.emit(f"Copied {what} to clipboard (tab-separated)")

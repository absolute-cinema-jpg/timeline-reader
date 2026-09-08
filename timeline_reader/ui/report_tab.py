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

from ..exporters import rows_to_delimited, write_delimited
from ..models import Timeline
from ..parsers import ParseError, parse_timeline
from .widgets import DropZone, ReportTable, make_card, section_label

ReportFn = Callable[[Timeline], "tuple[list[str], list[list[str]]]"]

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
        report_fn: ReportFn,
        drop_title: str,
        drop_sub: str,
        export_basename: str,
        empty_hint: str,
        parent=None,
    ):
        super().__init__(parent)
        self._report_fn = report_fn
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
        root.addWidget(self.table, 1)

        root.addLayout(self._action_bar())
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

        bar.addWidget(QLabel("Format:"))
        self.fmt = QComboBox()
        self.fmt.addItems(["CSV (.csv)", "TSV (.tsv)"])
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
            self._headers, self._rows = self._report_fn(tl)
        except Exception as exc:  # noqa: BLE001
            self._on_failed(f"Report build failed: {exc}")
            return
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

    # ---- output -----------------------------------------------------------
    def _delimiter(self):
        return "," if self.fmt.currentIndex() == 0 else "\t"

    def _suggested_name(self):
        base = self._timeline.name if self._timeline else "report"
        base = "".join(c if c.isalnum() or c in "-_ " else "_" for c in base).strip() or "report"
        ext = ".csv" if self.fmt.currentIndex() == 0 else ".tsv"
        return f"{base}_{self._export_basename}{ext}"

    def _export(self):
        if not self._rows:
            return
        ext = ".csv" if self.fmt.currentIndex() == 0 else ".tsv"
        filt = "CSV (*.csv)" if ext == ".csv" else "TSV (*.tsv)"
        path, _ = QFileDialog.getSaveFileName(self, "Export report", self._suggested_name(), filt)
        if not path:
            return
        if not path.lower().endswith(ext):
            path += ext
        try:
            write_delimited(path, self._headers, self._rows, self._delimiter())
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        self.status.emit(f"Exported {len(self._rows)} rows → {path}")
        QMessageBox.information(
            self, "Export complete",
            f"Wrote {len(self._rows)} rows to:\n{path}",
        )

    def _copy(self):
        if not self._rows:
            return
        text = rows_to_delimited(self._headers, self._rows, "\t")
        QApplication.clipboard().setText(text)
        self.status.emit("Copied table to clipboard (tab-separated)")

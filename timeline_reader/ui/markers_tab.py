"""Markers tab: list and export a timeline's locators (markers).

Loads a timeline file off the UI thread and shows every marker found on the
selected sequence — record position, colour, comment, author — ready to copy or
export to CSV/TSV. Markers come from Avid bins (.avb); other formats simply show
no markers.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
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

from .. import settings
from ..exporters import (
    AvidMarker,
    MARKERS_KIND,
    export_table,
    format_at,
    format_labels,
    index_of_kind,
    kind_at,
    rows_to_delimited,
    write_avid_markers,
)
from ..models import Marker, Timeline
from ..timecode import frames_to_duration, frames_to_tc
from .report_tab import TIMELINE_EXTS, _ParseWorker
from .widgets import DropZone, ReportTable, make_card, section_label

_HEADERS = ["#", "Track", "Position", "Duration", "Colour", "Comment", "User", "Date"]


class MarkersTab(QWidget):
    status = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timeline: Timeline | None = None
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
        self.drop = DropZone(
            "Drop a timeline file",
            "Avid bin (.avb) carries timeline markers · EDL / AAF also accepted",
            TIMELINE_EXTS,
        )
        self.drop.fileSelected.connect(self._on_file)
        self.drop.setMinimumWidth(360)
        self.drop.setMaximumWidth(460)
        top.addWidget(self.drop)
        top.addWidget(self._info_card(), 1)
        root.addLayout(top)

        self.table = ReportTable()
        self.table.set_data(_HEADERS, [])
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
        self.stat_markers = self._stat("—", "MARKERS")
        self.stat_fps = self._stat("—", "FPS")
        stats.addLayout(self.stat_markers[0])
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
        self.row_count = QLabel("Load a timeline to list its markers")
        self.row_count.setObjectName("Hint")
        bar.addWidget(self.row_count)
        bar.addStretch(1)

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
        self._rows = [self._row(i, m, tl) for i, m in enumerate(tl.markers, 1)]
        self.table.set_data(_HEADERS, self._rows)
        meta = f"{tl.source_format} · {tl.fps:g} fps · {len(tl.markers)} markers"
        self.drop.show_loaded(tl.source_path, meta)
        self.format_badge.setText(tl.source_format)
        self.format_badge.show()
        self.seq_name.setText(tl.name or "(untitled sequence)")
        self._populate_sequences(tl)
        self.stat_markers[1].setText(str(len(tl.markers)))
        self.stat_fps[1].setText(f"{tl.fps:g}")
        warnings = list(tl.warnings)
        if not tl.markers:
            warnings.append("No markers found on this sequence.")
        if warnings:
            self.warn.setText("⚠ " + "  ".join(warnings))
            self.warn.show()
        else:
            self.warn.hide()
        self.row_count.setText(
            f"{len(self._rows)} marker{'s' if len(self._rows) != 1 else ''} ready to export"
        )
        self._update_actions()
        self.status.emit(
            f"Loaded {os.path.basename(tl.source_path)} — {len(self._rows)} markers"
        )

    def _row(self, n: int, m: Marker, tl: Timeline) -> list[str]:
        return [
            str(n),
            m.track,
            frames_to_tc(m.position, tl.fps, tl.drop),
            frames_to_duration(m.length, tl.fps) if m.length else "",
            m.colour,
            m.comment,
            m.user,
            m.date,
        ]

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
        self._rows = []
        self.table.set_data(_HEADERS, [])
        self.format_badge.hide()
        self.seq_row.hide()
        self.seq_name.setText("No file loaded")
        for _, v, _l in (self.stat_markers, self.stat_fps):
            v.setText("—")
        self.warn.hide()
        self.row_count.setText("Load a timeline to list its markers")
        self._update_actions()

    def _update_actions(self):
        has = bool(self._rows)
        self.export_btn.setEnabled(has)
        self.copy_btn.setEnabled(has)

    # ---- output -----------------------------------------------------------
    def _build_markers(self) -> list[AvidMarker]:
        """Round-trip the loaded markers to Avid's marker format (absolute TC)."""
        tl = self._timeline
        return [
            AvidMarker(
                position=tl.start_tc + m.position,
                track=m.track,
                colour=m.colour or "Red",
                name="",
                comment=m.comment,
                duration=m.length or 1,
                author=m.user,
            )
            for m in tl.markers
        ]

    def _base_name(self) -> str:
        base = self._timeline.name if self._timeline else "markers"
        base = "".join(c if c.isalnum() or c in "-_ " else "_" for c in base).strip()
        return base or "markers"

    def _suggested_name(self):
        _label, ext, _filt, _kind = format_at(self.fmt.currentIndex())
        return f"{self._base_name()}_markers{ext}"

    def _export(self):
        if not self._rows:
            return
        _label, ext, filt, kind = format_at(self.fmt.currentIndex())
        input_dir = os.path.dirname(os.path.abspath(self._path)) if self._path else ""
        start = settings.export_start_path(self._suggested_name(), input_dir)
        path, _ = QFileDialog.getSaveFileName(self, "Export markers", start, filt)
        if not path:
            return
        if not path.lower().endswith(ext):
            path += ext
        try:
            if kind == MARKERS_KIND:
                write_avid_markers(
                    path, self._build_markers(),
                    self._timeline.fps, self._timeline.drop,
                )
            else:
                export_table(path, list(_HEADERS), self._rows, kind,
                             sheet_name=f"{self._base_name()} markers")
        except (OSError, RuntimeError) as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        settings.remember_export_path(path)
        self.status.emit(f"Exported {len(self._rows)} markers → {path}")
        QMessageBox.information(
            self, "Export complete",
            f"Wrote {len(self._rows)} markers to:\n{path}",
        )

    def _copy(self):
        if not self._rows:
            return
        text = rows_to_delimited(_HEADERS, self._rows, "\t")
        QApplication.clipboard().setText(text)
        self.status.emit("Copied markers to clipboard (tab-separated)")

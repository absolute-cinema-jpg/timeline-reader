"""Music Tracker tab: merge a timeline's music into cues and export the table.

Same layout and shortcuts as the Opticals / Clip List tabs — a drop zone, an
info card with selection-aware stats, a toolbar row with the sequence picker,
column chooser and clear-selection, a sortable/reorderable table, and an action
bar with format, copy and export — plus a music-options card for choosing which
sound tracks hold the music and how cues are merged.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import music, settings
from ..columns import ColumnSelection
from ..exporters import (
    export_table,
    format_at,
    format_labels,
    index_of_kind,
    kind_at,
    rows_to_delimited,
)
from ..models import Timeline
from ..timecode import frames_to_duration
from .column_dialog import ColumnDialog
from .report_tab import TIMELINE_EXTS, _ParseWorker
from .widgets import DropZone, ReportTable, make_card, section_label


class MusicTab(QWidget):
    status = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selection = ColumnSelection(music.REPORT_KEY).load()
        self._timeline: Timeline | None = None
        self._cues: list[music.MusicCue] = []
        self._rows: list[list[str]] = []
        self._headers: list[str] = []
        self._col_ids: list[str] = []
        self._row_durations: list[int] = []
        self._worker: _ParseWorker | None = None
        self._path: str = ""
        self._suppress_switch = False
        self._suppress_recompute = False
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
            "Avid bin (.avb) carries music tracks · EDL / AAF also accepted",
            TIMELINE_EXTS,
        )
        self.drop.fileSelected.connect(self._on_file)
        self.drop.setMinimumWidth(360)
        self.drop.setMaximumWidth(460)
        top.addWidget(self.drop)
        top.addWidget(self._info_card(), 1)
        root.addLayout(top)

        root.addWidget(self._options_card())

        self.table = ReportTable()
        self.table.setToolTip(
            "Exports every row by default. Select rows to export just those "
            "(⌘/Shift-click for more); Esc or ⌘⇧A goes back to all."
        )
        self.table.set_data(music.HEADERS_HINT, [])
        self.table.horizontalHeader().sectionMoved.connect(self._on_section_moved)

        root.addLayout(self._toolbar())
        root.addWidget(self.table, 1)
        root.addLayout(self._action_bar())

        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._deselect_sc = QShortcut(QKeySequence("Ctrl+Shift+A"), self)
        self._deselect_sc.setContext(Qt.WidgetWithChildrenShortcut)
        self._deselect_sc.activated.connect(self.table.clearSelection)

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

        stats = QHBoxLayout()
        stats.setSpacing(28)
        self.stat_count = self._stat("—", "CUES")
        self.stat_duration = self._stat("—", "DURATION")
        stats.addLayout(self.stat_count[0])
        stats.addLayout(self.stat_duration[0])
        stats.addStretch(1)
        lay.addLayout(stats)

        self.warn = QLabel("")
        self.warn.setObjectName("WarnLabel")
        self.warn.setWordWrap(True)
        self.warn.hide()
        lay.addWidget(self.warn)
        lay.addStretch(1)
        return card

    def _options_card(self):
        card = make_card()
        lay = QHBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(22)

        tracks_box = QVBoxLayout()
        tracks_box.setSpacing(4)
        tracks_box.addWidget(section_label("Music tracks"))
        self.track_list = QListWidget()
        self.track_list.setSelectionMode(QListWidget.NoSelection)
        self.track_list.setFlow(QListWidget.LeftToRight)
        self.track_list.setWrapping(True)
        self.track_list.setFixedHeight(60)
        self.track_list.itemChanged.connect(self._on_tracks_changed)
        tracks_box.addWidget(self.track_list)
        self.tracks_hint = QLabel("Load a timeline, then tick the tracks your music sits on")
        self.tracks_hint.setObjectName("Hint")
        self.tracks_hint.setWordWrap(True)
        tracks_box.addWidget(self.tracks_hint)
        lay.addLayout(tracks_box, 1)

        controls = QVBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(section_label("Cue options"))
        gap_row = QHBoxLayout()
        gap_row.setSpacing(8)
        gap_row.addWidget(QLabel("End cue after gap:"))
        self.gap = QDoubleSpinBox()
        self.gap.setRange(0.0, 60.0)
        self.gap.setSingleStep(0.5)
        self.gap.setDecimals(1)
        self.gap.setSuffix(" s")
        self.gap.setValue(settings.music_gap_seconds())
        self.gap.valueChanged.connect(self._on_option_changed)
        gap_row.addWidget(self.gap)
        gap_row.addStretch(1)
        controls.addLayout(gap_row)

        self.dissolves = QCheckBox("Include cross dissolves in TC in / out")
        self.dissolves.setChecked(settings.music_include_dissolves())
        self.dissolves.toggled.connect(self._on_option_changed)
        controls.addWidget(self.dissolves)

        self.muted_cb = QCheckBox("Include muted clips (adds a Muted column)")
        self.muted_cb.setChecked(settings.music_include_muted())
        self.muted_cb.toggled.connect(self._on_option_changed)
        controls.addWidget(self.muted_cb)
        controls.addStretch(1)
        lay.addLayout(controls, 1)
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

    def _toolbar(self):
        bar = QHBoxLayout()
        bar.setSpacing(8)

        self.seq_row = QWidget()
        seq_lay = QHBoxLayout(self.seq_row)
        seq_lay.setContentsMargins(0, 0, 0, 0)
        seq_lay.setSpacing(8)
        seq_lay.addWidget(QLabel("Sequence:"))
        self.seq_combo = QComboBox()
        self.seq_combo.setMinimumWidth(240)
        self.seq_combo.currentIndexChanged.connect(self._switch_sequence)
        seq_lay.addWidget(self.seq_combo)
        self.seq_row.hide()
        bar.addWidget(self.seq_row)

        self.columns_btn = QPushButton("Choose columns…")
        self.columns_btn.clicked.connect(self._choose_columns)
        bar.addWidget(self.columns_btn)

        self.clear_sel_btn = QPushButton("Clear selection")
        self.clear_sel_btn.clicked.connect(self.table.clearSelection)
        bar.addWidget(self.clear_sel_btn)

        bar.addStretch(1)
        return bar

    def _action_bar(self):
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.row_count = QLabel("Load a timeline to build the music tracker")
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
        meta = f"{tl.source_format} · {tl.fps:g} fps · {len(tl.audio_clips)} audio clips"
        self.drop.show_loaded(tl.source_path, meta)
        self.format_badge.setText(tl.source_format)
        self.format_badge.show()
        self.seq_name.setText(tl.name or "(untitled sequence)")
        self._populate_sequences(tl)
        self._populate_tracks(tl)
        self._recompute()
        self.status.emit(f"Loaded {os.path.basename(tl.source_path)}")

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

    def _populate_tracks(self, tl: Timeline):
        """Fill the track picker with the sound tracks that carry audio, re-ticking
        the ones the user chose last time where they exist in this file."""
        tracks = music.available_tracks(tl)
        remembered = set(settings.music_tracks())
        self._suppress_recompute = True
        self.track_list.clear()
        for name in tracks:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if name in remembered else Qt.Unchecked)
            self.track_list.addItem(item)
        self._suppress_recompute = False
        if tracks:
            self.tracks_hint.setText(
                f"{len(tracks)} sound track{'s' if len(tracks) != 1 else ''} with audio — "
                "tick the ones holding your music"
            )
        else:
            self.tracks_hint.setText("No audio found on this timeline")

    def _checked_tracks(self) -> list[str]:
        return [
            self.track_list.item(i).text()
            for i in range(self.track_list.count())
            if self.track_list.item(i).checkState() == Qt.Checked
        ]

    def _on_tracks_changed(self, *_):
        if self._suppress_recompute:
            return
        settings.set_music_tracks(self._checked_tracks())
        self._recompute()

    def _on_option_changed(self, *_):
        settings.set_music_gap_seconds(self.gap.value())
        settings.set_music_include_dissolves(self.dissolves.isChecked())
        settings.set_music_include_muted(self.muted_cb.isChecked())
        self._recompute()

    # ---- report build -----------------------------------------------------
    def _recompute(self):
        if self._timeline is None:
            return
        tracks = self._checked_tracks()
        self._cues, cols, self._rows = music.build_rows(
            self._timeline,
            tracks,
            self._selection,
            gap_seconds=self.gap.value(),
            include_dissolves=self.dissolves.isChecked(),
            include_muted=self.muted_cb.isChecked(),
        )
        self._col_ids = [c.id for c in cols]
        self._headers = [c.label for c in cols]
        self._row_durations = [cue.duration for cue in self._cues]
        self.table.set_data(self._headers, self._rows)
        self._update_stats()

        warnings = list(self._timeline.warnings)
        if not tracks:
            warnings.append("Tick the sound tracks your music sits on to build the report.")
        elif not self._rows:
            warnings.append("No music cues found on the selected tracks.")
        if warnings:
            self.warn.setText("⚠ " + "  ".join(warnings))
            self.warn.show()
        else:
            self.warn.hide()

        self.row_count.setText(
            f"{len(self._rows)} cue{'s' if len(self._rows) != 1 else ''} ready to export"
            if self._rows else "No cues to export"
        )
        self._update_actions()

    def _choose_columns(self):
        if self._timeline is None:
            return
        cols = music.all_columns(self.muted_cb.isChecked())
        dlg = ColumnDialog(cols, self._selection, self)
        if dlg.exec():
            self._recompute()

    def _on_section_moved(self, logical: int, old_visual: int, new_visual: int):
        """User dragged a table header: persist the new order and rebuild so the
        model, export and saved order all agree (the header resets to identity)."""
        if not self._col_ids or self._timeline is None:
            return
        header = self.table.horizontalHeader()
        n = len(self._col_ids)
        visible_order = [self._col_ids[header.logicalIndex(v)] for v in range(n)]
        hidden = [cid for cid in self._selection.order if cid not in visible_order]
        self._selection.set_order(visible_order + hidden)
        self._selection.save()
        self._recompute()
        self.status.emit("Columns reordered")

    # ---- selection / stats ------------------------------------------------
    def _update_actions(self):
        has = bool(self._rows)
        self.export_btn.setEnabled(has)
        self.copy_btn.setEnabled(has)
        self.columns_btn.setEnabled(self._timeline is not None)
        self._on_selection_changed()

    def _on_selection_changed(self, *_):
        n = len(self.table.selected_rows()) if self._rows else 0
        self.export_btn.setText(f"Export {n} selected…" if n else "Export all…")
        self.clear_sel_btn.setEnabled(n > 0)
        self._update_stats()

    def _update_stats(self):
        if not self._rows:
            self.stat_count[1].setText("—")
            self.stat_count[2].setText("CUES")
            self.stat_duration[1].setText("—")
            return
        sel = self.table.selected_rows()
        idxs = sel if sel else range(len(self._rows))
        total = sum(self._row_durations[i] for i in idxs if i < len(self._row_durations))
        fps = self._timeline.fps if self._timeline else 25.0
        self.stat_count[1].setText(str(len(sel) if sel else len(self._rows)))
        self.stat_count[2].setText("SELECTED" if sel else "CUES")
        self.stat_duration[1].setText(frames_to_duration(total, fps))

    def _on_failed(self, message: str):
        QGuiApplication.restoreOverrideCursor()
        self.status.emit("Load failed")
        QMessageBox.warning(self, "Could not load file", message)
        self._update_actions()

    def _reset(self):
        self._timeline = None
        self._path = ""
        self._cues, self._rows = [], []
        self._headers, self._col_ids, self._row_durations = [], [], []
        self.table.set_data(music.HEADERS_HINT, [])
        self._suppress_recompute = True
        self.track_list.clear()
        self._suppress_recompute = False
        self.format_badge.hide()
        self.seq_row.hide()
        self.seq_name.setText("No file loaded")
        self.tracks_hint.setText("Load a timeline, then tick the tracks your music sits on")
        self._update_stats()
        self.warn.hide()
        self.row_count.setText("Load a timeline to build the music tracker")
        self._update_actions()

    # ---- output -----------------------------------------------------------
    def _base_name(self) -> str:
        base = self._timeline.name if self._timeline else "music"
        base = "".join(c if c.isalnum() or c in "-_ " else "_" for c in base).strip()
        return base or "music"

    def _suggested_name(self):
        _label, ext, _filt, _kind = format_at(self.fmt.currentIndex())
        return f"{self._base_name()}_music{ext}"

    def _selected_or_all_rows(self):
        sel = self.table.selected_rows()
        if sel:
            return [self._rows[i] for i in sel], True
        return self._rows, False

    def _export(self):
        if not self._rows:
            return
        rows, is_selection = self._selected_or_all_rows()
        _label, ext, filt, kind = format_at(self.fmt.currentIndex())
        input_dir = os.path.dirname(os.path.abspath(self._path)) if self._path else ""
        start = settings.export_start_path(self._suggested_name(), input_dir)
        path, _ = QFileDialog.getSaveFileName(self, "Export music tracker", start, filt)
        if not path:
            return
        if not path.lower().endswith(ext):
            path += ext
        try:
            export_table(
                path, self._headers, rows, kind,
                sheet_name=f"{self._base_name()} music",
            )
        except (OSError, RuntimeError) as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        settings.remember_export_path(path)
        what = f"{len(rows)} selected cues" if is_selection else f"{len(rows)} cues"
        self.status.emit(f"Exported {what} → {path}")
        QMessageBox.information(
            self, "Export complete", f"Wrote {what} to:\n{path}",
        )

    def _copy(self):
        if not self._rows:
            return
        rows, is_selection = self._selected_or_all_rows()
        text = rows_to_delimited(self._headers, rows, "\t")
        QApplication.clipboard().setText(text)
        what = f"{len(rows)} selected cues" if is_selection else "table"
        self.status.emit(f"Copied {what} to clipboard (tab-separated)")

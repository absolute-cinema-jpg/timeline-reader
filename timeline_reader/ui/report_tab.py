"""Base tab for timeline-driven reports (Opticals list, Clip list).

Loads a timeline file (bin / EDL / AAF / tab-delimited) off the UI thread,
builds a table via an injected report function, and exports to CSV/TSV.
"""

from __future__ import annotations

import os
from typing import Callable

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
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
    AVID_MARKER_COLOURS,
    AvidMarker,
    MARKERS_KIND,
    export_table,
    format_at,
    format_labels,
    index_of_kind,
    kind_at,
    markers_to_text,
    rows_to_delimited,
    write_avid_markers,
)
from ..models import Timeline
from ..loader import load_timeline
from ..parsers import ParseError
from ..rowset import RowSet
from ..timecode import frames_to_duration
from .column_dialog import ColumnDialog
from .widgets import DropZone, LoadWorkers, ReportTable, make_card, section_label

TIMELINE_EXTS = [".avb", ".edl", ".aaf", ".txt", ".tsv", ".tab"]


class _ParseWorker(QThread):
    """Parse off the UI thread. Every timeline tab loads the same file at once,
    so this goes through the shared loader: one tab's worker does the parse and
    the rest pick up the cached result (see :mod:`timeline_reader.loader`)."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, path: str, key: int | None = None):
        super().__init__()
        self._path = path
        self._key = key

    def run(self):
        try:
            tl = load_timeline(self._path, self._key)
            self.done.emit(tl)
        except ParseError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"Unexpected error: {exc}")


class TimelineReportTab(QWidget):
    status = Signal(str)
    # (path, key) after the user picks a sequence, so sibling tabs can follow.
    sequenceChanged = Signal(str, int)

    def __init__(
        self,
        report: Report,
        drop_title: str,
        drop_sub: str,
        export_basename: str,
        empty_hint: str,
        count_label: str = "Clips",
        parent=None,
    ):
        super().__init__(parent)
        self._report = report
        self._selection = ColumnSelection(report.key).load()
        self._export_basename = export_basename
        self._empty_hint = empty_hint
        self._count_label = count_label
        self._drop_title_text = drop_title
        self._drop_sub_text = drop_sub
        self._timeline: Timeline | None = None
        self._headers: list[str] = []
        self._rows: list[list[str]] = []
        self._row_durations: list[int] = []
        self._workers = LoadWorkers(self._on_parsed, self._on_failed, parent=self)
        self._path: str = ""
        self._seq_key: int | None = None  # sequence requested within the file
        self._suppress_switch = False
        self._col_ids: list[str] = []
        self._all_contexts: list = []       # every row from the loaded sequence
        self._active_contexts: list = []     # the ones still shown (after deletions)
        self._rowset = RowSet()              # which rows are deleted
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
            "(⌘/Shift-click for more); Esc or ⌘⇧A goes back to all."
        )
        self.table.horizontalHeader().sectionMoved.connect(self._on_section_moved)

        root.addLayout(self._toolbar())  # sits above the table
        root.addWidget(self.table, 1)

        root.addLayout(self._action_bar())
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)

        # Deselect all — standard chord, works from anywhere in this tab.
        self._deselect_sc = QShortcut(QKeySequence("Ctrl+Shift+A"), self)
        self._deselect_sc.setContext(Qt.WidgetWithChildrenShortcut)
        self._deselect_sc.activated.connect(self.table.clearSelection)

        # Delete/Backspace removes selected rows; ⌘Z undoes the last deletion.
        self.table.deleteKeyPressed.connect(self._delete_selected)
        self._undo_sc = QShortcut(QKeySequence.StandardKey.Undo, self)
        self._undo_sc.setContext(Qt.WidgetWithChildrenShortcut)
        self._undo_sc.activated.connect(self._undo_delete)

        self._update_actions()

    def _toolbar(self):
        """Thin row between the top cards and the table: sequence picker (when a
        bin/AAF holds more than one), column chooser and a clear-selection button."""
        bar = QHBoxLayout()
        bar.setSpacing(8)

        # Sequence picker — leftmost; shown only when there's more than one.
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

        # Restore deleted rows — only visible once something has been deleted.
        self.reset_rows_btn = QPushButton("Reset rows")
        self.reset_rows_btn.setToolTip("Bring back every row deleted since the file loaded")
        self.reset_rows_btn.clicked.connect(self._reset_rows)
        self.reset_rows_btn.hide()
        bar.addWidget(self.reset_rows_btn)

        bar.addStretch(1)
        return bar

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
        self.stat_count = self._stat("—", self._count_label.upper())
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

        # Marker-colour override — left of Format, only shown for Markers (.txt).
        self.colour_label = QLabel("Marker colour:")
        bar.addWidget(self.colour_label)
        self.colour_combo = QComboBox()
        self.colour_combo.addItems(AVID_MARKER_COLOURS)  # defaults to Red (first)
        bar.addWidget(self.colour_combo)

        bar.addWidget(QLabel("Format:"))
        self.fmt = QComboBox()
        self.fmt.addItems(format_labels())
        self.fmt.setCurrentIndex(index_of_kind(settings.export_format_kind()))
        self.fmt.currentIndexChanged.connect(self._on_format_changed)
        bar.addWidget(self.fmt)

        self.copy_btn = QPushButton("Copy")
        self.copy_btn.clicked.connect(self._copy)
        bar.addWidget(self.copy_btn)

        self.export_btn = QPushButton("Export…")
        self.export_btn.setObjectName("Primary")
        self.export_btn.clicked.connect(self._export)
        bar.addWidget(self.export_btn)
        self._sync_colour_visibility()
        return bar

    def _on_format_changed(self, index: int):
        settings.set_export_format_kind(kind_at(index))
        self._sync_colour_visibility()

    def _sync_colour_visibility(self):
        show = kind_at(self.fmt.currentIndex()) == MARKERS_KIND
        self.colour_label.setVisible(show)
        self.colour_combo.setVisible(show)

    def _marker_colour(self) -> str:
        """The chosen marker colour (defaults to Red)."""
        return self.colour_combo.currentText() or "Red"

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
        self.sequenceChanged.emit(self._path, index)

    def set_sequence(self, path: str, key: int):
        """Follow a sequence picked in a sibling tab (no re-emit)."""
        if path == self._path and key == self._seq_key:
            return
        self._path = path
        self._load(path, key=key)

    def _load(self, path: str, key: int | None):
        self._seq_key = key
        self.status.emit(f"Reading {os.path.basename(path)}…")
        QGuiApplication.setOverrideCursor(Qt.BusyCursor)
        self.export_btn.setEnabled(False)
        self.drop.begin_loading(path)
        worker = _ParseWorker(path, key)
        worker.finished.connect(lambda: QGuiApplication.restoreOverrideCursor())
        self._workers.start(worker)

    def _on_parsed(self, tl: Timeline):
        self._timeline = tl
        try:
            self._all_contexts = self._compute_contexts()
        except Exception as exc:  # noqa: BLE001
            self._on_failed(f"Report build failed: {exc}")
            return
        self._rowset = RowSet()  # a fresh file starts with nothing deleted
        self._rebuild_rows()
        meta = f"{tl.source_format} · {tl.fps:g} fps · {len(tl.clips)} clips"
        self.drop.show_loaded(tl.source_path, meta)
        self.format_badge.setText(tl.source_format)
        self.format_badge.show()
        self.seq_name.setText(tl.name or "(untitled sequence)")
        self._populate_sequences(tl)
        self._update_stats()
        if tl.warnings:
            self.warn.setText("⚠ " + "  ".join(tl.warnings))
            self.warn.show()
        else:
            self.warn.hide()
        self._update_actions()
        self.status.emit(
            f"Loaded {os.path.basename(tl.source_path)} — {len(self._rows)} rows"
        )

    def _compute_contexts(self) -> list:
        """The report rows (contexts) for the loaded timeline. A subclass can
        override to filter — e.g. the Tag Finder narrows to notes matching a
        search — resetting its RowSet when the result set changes."""
        return list(self._report.iter_ctx(self._timeline))

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
        self._seq_key = current
        self.seq_combo.setCurrentIndex(current)
        self._suppress_switch = False
        self.seq_row.show()

    def _on_failed(self, message: str):
        QGuiApplication.restoreOverrideCursor()
        self.drop.end_loading()
        self.status.emit("Load failed")
        QMessageBox.warning(self, "Could not load file", message)
        self._update_actions()

    def _reset(self):
        self._timeline = None
        self._path = ""
        self._seq_key = None
        self._headers, self._rows = [], []
        self._row_durations = []
        self._all_contexts, self._active_contexts = [], []
        self._rowset = RowSet()
        self.reset_rows_btn.hide()
        self.table.set_data([], [])
        self.format_badge.hide()
        self.seq_row.hide()
        self.seq_name.setText("No file loaded")
        self._update_stats()
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
        """Keep the export controls and count label in sync with the row selection
        so it's always clear whether you'll export everything or just the
        highlighted rows."""
        total = len(self._rows)
        n = len(self.table.selected_rows()) if self._rows else 0
        self.export_btn.setText(f"Export {n} selected…" if n else "Export all…")
        self.clear_sel_btn.setEnabled(n > 0)
        if not total:
            self.row_count.setText(self._empty_hint)
        elif n:
            self.row_count.setText(f"{n} of {total} rows selected")
        else:
            noun = "row" if total == 1 else "rows"
            self.row_count.setText(f"{total} {noun} ready to export")
        self._update_stats()

    def _update_stats(self):
        """Show the count and total duration for the current selection, or for the
        whole report when nothing is selected."""
        if not self._rows:
            self.stat_count[1].setText("—")
            self.stat_count[2].setText(self._count_label.upper())
            self.stat_duration[1].setText("—")
            return
        sel = self.table.selected_rows()
        idxs = sel if sel else range(len(self._rows))
        total = sum(
            self._row_durations[i] for i in idxs if i < len(self._row_durations)
        )
        fps = self._timeline.fps if self._timeline else 25.0
        self.stat_count[1].setText(str(len(sel) if sel else len(self._rows)))
        self.stat_count[2].setText("SELECTED" if sel else self._count_label.upper())
        self.stat_duration[1].setText(frames_to_duration(total, fps))

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
        cols = self._report.columns_for(self._timeline, self._selection)
        self._col_ids = [c.id for c in cols]
        self._headers = [c.label for c in cols]
        keys = list(range(len(self._all_contexts)))
        self._active_contexts = self._rowset.active_items(keys, self._all_contexts)
        for pos, ctx in enumerate(self._active_contexts, 1):
            ctx.n = pos  # renumber the "#" column contiguously after deletions
        self._rows = [[c.getter(ctx) for c in cols] for ctx in self._active_contexts]
        self._row_durations = [ctx.clip.duration for ctx in self._active_contexts]
        self.table.set_data(self._headers, self._rows)
        self.reset_rows_btn.setVisible(self._rowset.has_deletions)
        self._update_stats()
        self._update_actions()

    # ---- row deletion / undo / reset --------------------------------------
    def _delete_selected(self):
        if self._timeline is None:
            return
        sel = self.table.selected_rows()
        if not sel:
            return
        active_keys = self._rowset.active_keys(range(len(self._all_contexts)))
        n = self._rowset.delete_display(sel, active_keys)
        if not n:
            return
        self.table.clearSelection()
        self._rebuild_rows()
        self.status.emit(f"Deleted {n} row{'s' if n != 1 else ''} — ⌘Z to undo")

    def _undo_delete(self):
        if self._timeline is None or not self._rowset.can_undo:
            return
        n = self._rowset.undo()
        self._rebuild_rows()
        self.status.emit(f"Restored {n} row{'s' if n != 1 else ''}")

    def _reset_rows(self):
        if not self._rowset.has_deletions:
            return
        self._rowset.reset()
        self._rebuild_rows()
        self.status.emit("Restored all rows")

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
        # Default filename is the chosen sequence's name (+ _markers for markers).
        _label, ext, _filt, kind = format_at(self.fmt.currentIndex())
        suffix = "_markers" if kind == MARKERS_KIND else ""
        return f"{self._base_name()}{suffix}{ext}"

    def _selected_or_all_rows(self):
        """Rows to output: just the selected ones (in on-screen order) if the
        user has a selection, otherwise the whole report."""
        sel = self.table.selected_rows()
        if sel:
            return [self._rows[i] for i in sel], True
        return self._rows, False

    def _selected_indices(self):
        """Row indices to output (selection, else all) — the on-screen order."""
        sel = self.table.selected_rows()
        return sel if sel else list(range(len(self._rows)))

    def _build_markers(self, indices) -> list[AvidMarker]:
        """One Avid marker per chosen row, at the clip's absolute record TC."""
        tl = self._timeline
        colour = self._marker_colour()
        markers = []
        for i in indices:
            if i >= len(self._active_contexts):
                continue
            ctx = self._active_contexts[i]
            markers.append(AvidMarker(
                position=tl.start_tc + ctx.clip.rec_start,
                track=ctx.clip.track,
                colour=colour,
                name=self._report.marker_name(ctx) if self._report.marker_name else "",
                comment=self._report.marker_comment(ctx) if self._report.marker_comment else "",
            ))
        return markers

    def _export(self):
        if not self._rows:
            return
        indices = self._selected_indices()
        is_selection = bool(self.table.selected_rows())
        _label, ext, filt, kind = format_at(self.fmt.currentIndex())
        input_dir = os.path.dirname(os.path.abspath(self._path)) if self._path else ""
        start = settings.export_start_path(self._suggested_name(), input_dir)
        path, _ = QFileDialog.getSaveFileName(self, "Export report", start, filt)
        if not path:
            return
        if not path.lower().endswith(ext):
            path += ext
        try:
            if kind == MARKERS_KIND:
                write_avid_markers(
                    path, self._build_markers(indices),
                    self._timeline.fps, self._timeline.drop,
                )
            else:
                rows = [self._rows[i] for i in indices]
                export_table(path, self._headers, rows, kind, sheet_name=self._base_name())
        except (OSError, RuntimeError) as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        settings.remember_export_path(path)
        noun = "markers" if kind == MARKERS_KIND else "rows"
        what = f"{len(indices)} selected {noun}" if is_selection else f"{len(indices)} {noun}"
        self.status.emit(f"Exported {what} → {path}")
        QMessageBox.information(
            self, "Export complete",
            f"Wrote {what} to:\n{path}",
        )

    def _copy(self):
        if not self._rows:
            return
        is_selection = bool(self.table.selected_rows())
        if kind_at(self.fmt.currentIndex()) == MARKERS_KIND:
            markers = self._build_markers(self._selected_indices())
            text = markers_to_text(markers, self._timeline.fps, self._timeline.drop)
            QApplication.clipboard().setText(text)
            what = f"{len(markers)} selected markers" if is_selection else f"{len(markers)} markers"
            self.status.emit(f"Copied {what} to clipboard (.txt)")
            return
        rows, is_selection = self._selected_or_all_rows()
        text = rows_to_delimited(self._headers, rows, "\t")
        QApplication.clipboard().setText(text)
        what = f"{len(rows)} selected rows" if is_selection else "table"
        self.status.emit(f"Copied {what} to clipboard (tab-separated)")

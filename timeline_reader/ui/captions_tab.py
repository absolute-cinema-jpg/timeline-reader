"""Captions → SRT tab.

Reads subtitles straight from an Avid bin (.avb): every Avid *SubCap* subtitle on
the timeline becomes a cue, timed by where it sits and carrying its own text
(multi-line captions included). An Avid DS Caption (.txt) export is still
accepted as a fallback. The SubRip preview is editable, and edits carry through
to Copy / Export.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import settings
from ..captions import CaptionDoc, parse_caption_file, to_srt, visible_cues
from ..exporters import write_text
from ..loader import load_captions
from ..parsers import ParseError
from .widgets import DropZone, make_card, section_label

# Extensions handled here: an Avid bin, or a DS Caption text export.
BIN_EXT = ".avb"
CAPTION_EXTS = [BIN_EXT, ".txt"]

_FPS_CHOICES = [
    ("23.976", 24000 / 1001, False),
    ("24", 24.0, False),
    ("25 (PAL)", 25.0, False),
    ("29.97 DF", 30000 / 1001, True),
    ("29.97 NDF", 30000 / 1001, False),
    ("30", 30.0, False),
    ("50", 50.0, False),
    ("59.94", 60000 / 1001, False),
    ("60", 60.0, False),
]


class _CaptionWorker(QThread):
    """Read a bin's subtitles off the UI thread. The bin is the same file the
    other tabs are loading at the same moment, so this goes through the shared
    loader and normally just picks up the parse another tab's worker did."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, path: str, key: int | None = None):
        super().__init__()
        self._path = path
        self._key = key

    def run(self):
        try:
            self.done.emit(load_captions(self._path, self._key))
        except ParseError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"Unexpected error: {exc}")


def _fps_preset_index(fps: float, drop: bool) -> int | None:
    """The frame-rate combo index closest to a detected sequence rate, if any.

    Matches on the actual rate, not a rounded one, so 23.976 and 24 (and 29.97
    vs 30, 59.94 vs 60) stay distinct — rounding would collapse them and, since
    23.976 is listed first, silently mislabel every 24 fps sequence as 23.976.
    """
    best_i, best_diff = None, None
    for i, (_, f, d) in enumerate(_FPS_CHOICES):
        if d != drop:
            continue
        diff = abs(f - fps)
        if best_diff is None or diff < best_diff:
            best_i, best_diff = i, diff
    # Only accept a genuinely close match (within half a frame per second).
    if best_i is not None and best_diff <= 0.5:
        return best_i
    return None


class CaptionsTab(QWidget):
    status = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = ""
        self._doc: CaptionDoc | None = None
        self._srt = ""
        self._seq_key: int | None = None      # chosen sequence within a bin
        self._loading = False                  # replacing the preview programmatically
        self._worker: _CaptionWorker | None = None
        self._suppress_switch = False          # populating the sequence combo
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(14)

        top = QHBoxLayout()
        top.setSpacing(14)
        self.drop = DropZone(
            "Drop an Avid bin (.avb)",
            "SubCap subtitles read straight from the timeline · DS Caption .txt also accepted",
            CAPTION_EXTS,
        )
        self.drop.fileSelected.connect(self._on_file)
        self.drop.setMinimumWidth(360)
        self.drop.setMaximumWidth(460)
        top.addWidget(self.drop)
        top.addWidget(self._options_card(), 1)
        root.addLayout(top)

        prev_head = QHBoxLayout()
        prev_head.addWidget(section_label("SRT Preview (editable)"))
        prev_head.addStretch(1)
        self.cue_count = QLabel("")
        self.cue_count.setObjectName("Hint")
        prev_head.addWidget(self.cue_count)
        root.addLayout(prev_head)

        self.preview = QPlainTextEdit()
        self.preview.setPlaceholderText(
            "The SubRip (.srt) subtitles will appear here once a bin is loaded. "
            "You can edit them before exporting."
        )
        self.preview.textChanged.connect(self._on_preview_edited)
        root.addWidget(self.preview, 1)

        root.addLayout(self._action_bar())
        self._update_actions()

    def _options_card(self):
        card = make_card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)
        lay.addWidget(section_label("Options"))

        # Sequence picker — shown only for a bin with more than one sequence.
        self.seq_row = QWidget()
        seq_lay = QHBoxLayout(self.seq_row)
        seq_lay.setContentsMargins(0, 0, 0, 0)
        seq_lay.setSpacing(10)
        seq_lay.addWidget(QLabel("Sequence:"))
        self.seq_combo = QComboBox()
        self.seq_combo.setMinimumWidth(240)
        self.seq_combo.currentIndexChanged.connect(self._switch_sequence)
        seq_lay.addWidget(self.seq_combo, 1)
        self.seq_row.hide()
        lay.addWidget(self.seq_row)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(QLabel("Frame rate:"))
        self.fps = QComboBox()
        for label, _, _ in _FPS_CHOICES:
            self.fps.addItem(label)
        self.fps.setCurrentIndex(settings.caption_fps_index(2))  # default 25 PAL
        self.fps.currentIndexChanged.connect(self._on_fps_changed)
        row.addWidget(self.fps)
        row.addStretch(1)
        lay.addLayout(row)

        self.muted_cb = QCheckBox("Include muted captions")
        self.muted_cb.setToolTip(
            "Captions on clips disabled in the Avid timeline are left out of the "
            "SRT. Tick to include them."
        )
        self.muted_cb.toggled.connect(self._on_include_muted_changed)
        lay.addWidget(self.muted_cb)

        self.fps_hint = QLabel(
            "Frame rate maps timecodes to SRT milliseconds. A bin sets this from "
            "the sequence, but you can override it — e.g. 24 vs 23.976, which Avid "
            "stores identically."
        )
        self.fps_hint.setObjectName("Hint")
        self.fps_hint.setWordWrap(True)
        lay.addWidget(self.fps_hint)

        self.info = QLabel("No file loaded")
        self.info.setObjectName("DropSub")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        lay.addStretch(1)
        return card

    def _action_bar(self):
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.summary = QLabel("Load an Avid bin to read its subtitles")
        self.summary.setObjectName("Hint")
        bar.addWidget(self.summary)
        bar.addStretch(1)
        self.copy_btn = QPushButton("Copy SRT")
        self.copy_btn.clicked.connect(self._copy)
        bar.addWidget(self.copy_btn)
        self.export_btn = QPushButton("Export .srt…")
        self.export_btn.setObjectName("Primary")
        self.export_btn.clicked.connect(self._export)
        bar.addWidget(self.export_btn)
        return bar

    # ---- loading ----------------------------------------------------------
    def _is_bin(self) -> bool:
        return self._path.lower().endswith(BIN_EXT)

    def _fps_drop(self):
        _, fps, drop = _FPS_CHOICES[self.fps.currentIndex()]
        return fps, drop

    def _on_file(self, path: str):
        self._path = path
        self._seq_key = None  # a new file starts at its default sequence
        if not path:
            self._reset()
            return
        self._reconvert()

    def _on_fps_changed(self, index: int):
        # Ignore the programmatic set that syncs the combo to a detected rate.
        if self._suppress_switch:
            return
        settings.set_caption_fps_index(index)
        if not self._path:
            return
        if self._is_bin():
            # A bin's cues are already parsed as frames; overriding the rate just
            # re-interprets those frames as milliseconds (24 vs 23.976), no reparse.
            if self._doc is not None:
                fps, drop = self._fps_drop()
                self._doc.fps, self._doc.drop = fps, drop
                self._render()
        else:
            self._reconvert()

    def _on_include_muted_changed(self, _checked: bool):
        # Muted cues are already parsed; including them is just a re-render.
        if self._doc is not None:
            self._render()

    def _render(self):
        """Rebuild the SRT from the current doc and options, without re-parsing."""
        if self._doc is None:
            return
        self._srt = to_srt(self._doc, include_muted=self.muted_cb.isChecked())
        self._set_preview(self._srt)
        self._refresh_labels()

    def _switch_sequence(self, index: int):
        if self._suppress_switch or not self._path or index < 0:
            return
        self._seq_key = index
        self._reconvert()

    def _reconvert(self):
        if not self._path:
            return
        ext = os.path.splitext(self._path)[1].lower()
        if ext == BIN_EXT:
            # A bin is read on a worker, like the other timeline tabs.
            self.status.emit(f"Reading {os.path.basename(self._path)}…")
            QGuiApplication.setOverrideCursor(Qt.BusyCursor)
            self._worker = _CaptionWorker(self._path, self._seq_key)
            self._worker.done.connect(self._on_doc)
            self._worker.failed.connect(self._on_failed)
            self._worker.finished.connect(lambda: QGuiApplication.restoreOverrideCursor())
            self._worker.start()
            return
        if ext != ".txt":
            self._unsupported(ext)
            return
        QGuiApplication.setOverrideCursor(Qt.BusyCursor)
        try:
            fps, drop = self._fps_drop()
            doc = parse_caption_file(self._path, fps=fps, drop=drop)
        except (ParseError, OSError, ValueError) as exc:
            self._on_failed(str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self._on_failed(f"Unexpected error: {exc}")
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        self._on_doc(doc)

    def _on_doc(self, doc: CaptionDoc):
        self._doc = doc
        self._srt = to_srt(doc, include_muted=self.muted_cb.isChecked())
        self._show_doc()

    def _show_doc(self):
        n = len(self._shown_cues())
        self._set_preview(self._srt)
        self._sync_fps_control(self._doc)
        self._populate_sequences(self._doc)
        self._refresh_labels()
        self.status.emit(f"Read {n} subtitles" if self._is_bin() else f"Converted {n} caption cues")

    def _shown_cues(self):
        if self._doc is None:
            return []
        return visible_cues(self._doc, self.muted_cb.isChecked())

    def _refresh_labels(self):
        """Update the loaded-file line, info and summary from the current doc —
        without touching the frame-rate control (so a manual override sticks)."""
        doc = self._doc
        if doc is None:
            return
        n = len(self._shown_cues())
        hidden = len(doc.cues) - n  # muted cues being left out
        muted_note = f" · {hidden} muted hidden" if hidden else ""
        if self._is_bin():
            seq = doc.sequence_name or os.path.basename(self._path)
            self.drop.show_loaded(
                self._path, f"{seq} · {n} subtitles · {doc.fps:g} fps{muted_note}"
            )
            self.info.setText(f"{seq}\n{n} SubCap subtitles on this sequence.")
        else:
            self.drop.show_loaded(self._path, f"{n} cues · {self.fps.currentText()}")
            self.info.setText(f"{os.path.basename(self._path)}\n{n} caption cues detected.")
        self.cue_count.setText(f"{n} cues")
        summary = f"{n} cues ready to export as SubRip"
        if hidden:
            summary += f" ({hidden} muted caption{'s' if hidden != 1 else ''} excluded)"
        self.summary.setText(summary)
        if doc.warnings:
            self.summary.setText("⚠ " + doc.warnings[0])
        self._update_actions()

    def _sync_fps_control(self, doc: CaptionDoc):
        """Set the control to the bin's detected rate, but leave it editable so the
        user can override an ambiguous rate (Avid stores 24 and 23.976 alike)."""
        if self._is_bin():
            idx = _fps_preset_index(doc.fps, doc.drop)
            if idx is not None:
                self._suppress_switch = True
                self.fps.setCurrentIndex(idx)
                self._suppress_switch = False
        self.fps.setEnabled(True)

    def _populate_sequences(self, doc: CaptionDoc):
        opts = doc.available_sequences
        if not self._is_bin() or len(opts) <= 1:
            self.seq_row.hide()
            return
        self._suppress_switch = True
        self.seq_combo.clear()
        for opt in opts:
            label = opt.name if not opt.detail else f"{opt.name}   ({opt.detail})"
            self.seq_combo.addItem(label)
        self.seq_combo.setCurrentIndex(doc.sequence_key or 0)
        self._suppress_switch = False
        self.seq_row.show()

    def _unsupported(self, ext: str):
        """A non-caption source (e.g. an EDL/AAF mirrored from another tab): keep a
        calm empty state rather than an error dialog."""
        self._doc = None
        self._srt = ""
        self._set_preview("")
        self.seq_row.hide()
        self.fps.setEnabled(True)
        self.cue_count.setText("")
        self.info.setText(
            f"{os.path.basename(self._path)}\nSubtitles are read from Avid bins "
            f"(.avb); {ext or 'this file'} isn't supported here."
        )
        self.summary.setText("Load an Avid bin (.avb) to read its subtitles")
        self._update_actions()

    def _on_failed(self, message: str):
        QGuiApplication.restoreOverrideCursor()
        self._doc = None
        self._srt = ""
        self._set_preview("")
        self._update_actions()
        self.status.emit("Caption load failed")
        QMessageBox.warning(self, "Could not read subtitles", message)

    def _reset(self):
        self._doc = None
        self._srt = ""
        self._seq_key = None
        self._set_preview("")
        self.seq_row.hide()
        self.fps.setEnabled(True)
        self.info.setText("No file loaded")
        self.cue_count.setText("")
        self.summary.setText("Load an Avid bin to read its subtitles")
        self._update_actions()

    # ---- preview / output -------------------------------------------------
    def _set_preview(self, text: str):
        """Replace the preview contents without treating it as a user edit."""
        self._loading = True
        try:
            self.preview.setPlainText(text)
        finally:
            self._loading = False

    def _current_srt(self) -> str:
        """The SRT to export/copy — the live (possibly edited) preview text."""
        return self.preview.toPlainText()

    def _on_preview_edited(self):
        if self._loading:
            return
        # The user has hand-edited the subtitles; keep export/copy in sync.
        self._update_actions()

    def _update_actions(self):
        has = bool(self._current_srt().strip())
        self.export_btn.setEnabled(has)
        self.copy_btn.setEnabled(has)

    def _suggested_name(self):
        if self._doc is not None and self._doc.sequence_name:
            base = self._doc.sequence_name
        elif self._path:
            base = os.path.splitext(os.path.basename(self._path))[0]
        else:
            base = "captions"
        return f"{base}.srt"

    def _export(self):
        srt = self._current_srt()
        if not srt.strip():
            return
        input_dir = os.path.dirname(os.path.abspath(self._path)) if self._path else ""
        start = settings.export_start_path(self._suggested_name(), input_dir)
        path, _ = QFileDialog.getSaveFileName(self, "Export SRT", start, "SubRip (*.srt)")
        if not path:
            return
        if not path.lower().endswith(".srt"):
            path += ".srt"
        try:
            write_text(path, srt)
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        settings.remember_export_path(path)
        self.status.emit(f"Exported SRT → {path}")
        QMessageBox.information(self, "Export complete", f"Wrote subtitles to:\n{path}")

    def _copy(self):
        srt = self._current_srt()
        if not srt.strip():
            return
        QApplication.clipboard().setText(srt)
        self.status.emit("Copied SRT to clipboard")

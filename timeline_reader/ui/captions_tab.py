"""Caption converter tab: Avid DS Caption (.txt) → SubRip (.srt)."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
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

from ..captions import CaptionDoc, parse_caption_file, to_srt
from ..exporters import write_text
from .widgets import DropZone, make_card, section_label

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


class CaptionsTab(QWidget):
    status = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = ""
        self._doc: CaptionDoc | None = None
        self._srt = ""
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(14)

        top = QHBoxLayout()
        top.setSpacing(14)
        self.drop = DropZone(
            "Drop an Avid DS Caption file",
            "Caption text export (.txt)",
            [".txt"],
        )
        self.drop.fileSelected.connect(self._on_file)
        self.drop.setMinimumWidth(360)
        self.drop.setMaximumWidth(460)
        top.addWidget(self.drop)
        top.addWidget(self._options_card(), 1)
        root.addLayout(top)

        prev_head = QHBoxLayout()
        prev_head.addWidget(section_label("SRT Preview"))
        prev_head.addStretch(1)
        self.cue_count = QLabel("")
        self.cue_count.setObjectName("Hint")
        prev_head.addWidget(self.cue_count)
        root.addLayout(prev_head)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText(
            "The converted SubRip (.srt) subtitles will appear here once a "
            "caption file is loaded."
        )
        root.addWidget(self.preview, 1)

        root.addLayout(self._action_bar())
        self._update_actions()

    def _options_card(self):
        card = make_card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)
        lay.addWidget(section_label("Conversion Options"))

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(QLabel("Frame rate:"))
        self.fps = QComboBox()
        for label, _, _ in _FPS_CHOICES:
            self.fps.addItem(label)
        self.fps.setCurrentIndex(2)  # 25 PAL — matches the sample project
        self.fps.currentIndexChanged.connect(self._reconvert)
        row.addWidget(self.fps)
        row.addStretch(1)
        lay.addLayout(row)

        hint = QLabel(
            "Frame rate controls how source timecodes convert to SRT "
            "milliseconds. Drop-frame is handled for 29.97/59.94."
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.info = QLabel("No file loaded")
        self.info.setObjectName("DropSub")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        lay.addStretch(1)
        return card

    def _action_bar(self):
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.summary = QLabel("Load an Avid DS Caption .txt to convert")
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

    # ---- logic ----
    def _fps_drop(self):
        _, fps, drop = _FPS_CHOICES[self.fps.currentIndex()]
        return fps, drop

    def _on_file(self, path: str):
        self._path = path
        if not path:
            self._reset()
            return
        self._reconvert()

    def _reconvert(self):
        if not self._path:
            return
        fps, drop = self._fps_drop()
        try:
            self._doc = parse_caption_file(self._path, fps=fps, drop=drop)
            self._srt = to_srt(self._doc)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Could not read caption file", str(exc))
            self.status.emit("Caption load failed")
            return
        n = len(self._doc.cues)
        self.preview.setPlainText(self._srt)
        self.drop.show_loaded(self._path, f"{n} cues · {self.fps.currentText()}")
        self.info.setText(f"{os.path.basename(self._path)}\n{n} caption cues detected.")
        self.cue_count.setText(f"{n} cues")
        self.summary.setText(f"{n} cues ready to export as SubRip")
        if self._doc.warnings:
            self.summary.setText("⚠ " + self._doc.warnings[0])
        self._update_actions()
        self.status.emit(f"Converted {n} caption cues")

    def _reset(self):
        self._doc = None
        self._srt = ""
        self.preview.clear()
        self.info.setText("No file loaded")
        self.cue_count.setText("")
        self.summary.setText("Load an Avid DS Caption .txt to convert")
        self._update_actions()

    def _update_actions(self):
        has = bool(self._srt.strip())
        self.export_btn.setEnabled(has)
        self.copy_btn.setEnabled(has)

    def _suggested_name(self):
        base = os.path.splitext(os.path.basename(self._path))[0] if self._path else "captions"
        return f"{base}.srt"

    def _export(self):
        if not self._srt:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export SRT", self._suggested_name(), "SubRip (*.srt)")
        if not path:
            return
        if not path.lower().endswith(".srt"):
            path += ".srt"
        try:
            write_text(path, self._srt)
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        self.status.emit(f"Exported SRT → {path}")
        QMessageBox.information(self, "Export complete", f"Wrote subtitles to:\n{path}")

    def _copy(self):
        if not self._srt:
            return
        QApplication.clipboard().setText(self._srt)
        self.status.emit("Copied SRT to clipboard")

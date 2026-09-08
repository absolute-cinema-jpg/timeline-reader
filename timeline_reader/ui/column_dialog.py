"""Dialog to include/exclude report columns, grouped by kind."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..columns import ColumnDef, ColumnSelection
from .widgets import section_label


class ColumnDialog(QDialog):
    """Lets the user pick which columns appear. Mutates ``selection`` on accept."""

    def __init__(self, columns: list[ColumnDef], selection: ColumnSelection, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose columns")
        self.setMinimumWidth(360)
        self._columns = columns
        self._selection = selection
        self._checks: dict[str, QCheckBox] = {}
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        intro = QLabel(
            "Tick the columns to include in the report and export. "
            "Metadata columns are read from the source file."
        )
        intro.setObjectName("Hint")
        intro.setWordWrap(True)
        root.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        col_lay = QVBoxLayout(inner)
        col_lay.setContentsMargins(2, 2, 2, 2)
        col_lay.setSpacing(4)

        current_group = None
        any_meta = False
        for col in self._columns:
            if col.group != current_group:
                if current_group is not None:
                    col_lay.addSpacing(6)
                col_lay.addWidget(section_label(col.group))
                current_group = col.group
            cb = QCheckBox(col.label)
            cb.setChecked(self._selection.effective(col))
            self._checks[col.id] = cb
            col_lay.addWidget(cb)
            if col.group == "Metadata":
                any_meta = True
        if not any_meta:
            note = QLabel("No extra metadata columns were found in this file.")
            note.setObjectName("Hint")
            note.setWordWrap(True)
            col_lay.addSpacing(6)
            col_lay.addWidget(section_label("Metadata"))
            col_lay.addWidget(note)
        col_lay.addStretch(1)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        reset = QPushButton("Reset to defaults")
        reset.clicked.connect(self._reset)
        root.addWidget(reset, 0, Qt.AlignLeft)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _reset(self):
        for col in self._columns:
            self._checks[col.id].setChecked(col.default)

    def accept(self):
        for col in self._columns:
            self._selection.set(col.id, self._checks[col.id].isChecked())
        self._selection.save()
        super().accept()

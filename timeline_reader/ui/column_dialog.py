"""Dialog to include/exclude report columns and drag to reorder them."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from ..columns import ColumnDef, ColumnSelection
from . import theme


class ColumnDialog(QDialog):
    """Pick which columns appear and in what order. Mutates ``selection`` on OK.

    The list is a single drag-to-reorder checklist: tick to include a column,
    drag a row to move it. Metadata columns are tinted so they stand out.
    """

    def __init__(self, columns: list[ColumnDef], selection: ColumnSelection, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Columns")
        self.setMinimumSize(340, 460)
        self._columns = {c.id: c for c in columns}
        self._all = columns
        self._selection = selection
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        intro = QLabel(
            "Tick columns to include them. Drag a row to change the order they "
            "appear in the table and the exported spreadsheet."
        )
        intro.setObjectName("Hint")
        intro.setWordWrap(True)
        root.addWidget(intro)

        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setDefaultDropAction(Qt.MoveAction)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setSpacing(1)
        root.addWidget(self.list, 1)
        self._populate(self._selection.ordered(self._all))

        reset = QPushButton("Reset to defaults")
        reset.clicked.connect(self._reset)
        root.addWidget(reset, 0, Qt.AlignLeft)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _populate(self, columns: list[ColumnDef]):
        self.list.clear()
        for col in columns:
            item = QListWidgetItem(col.label)
            flags = (
                Qt.ItemIsEnabled | Qt.ItemIsSelectable
                | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled
            )
            item.setFlags(flags)  # note: no DropEnabled -> rows can't nest
            item.setCheckState(Qt.Checked if self._selection.effective(col) else Qt.Unchecked)
            item.setData(Qt.UserRole, col.id)
            item.setToolTip(f"{col.group} column")
            if col.group == "Metadata":
                item.setForeground(QColor(theme.AMBER))
            self.list.addItem(item)

    def _reset(self):
        self._selection.reset()
        self._populate(self._all)  # canonical order, default checks

    def accept(self):
        order: list[str] = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            cid = item.data(Qt.UserRole)
            order.append(cid)
            self._selection.set(cid, item.checkState() == Qt.Checked)
        self._selection.set_order(order)
        self._selection.save()
        super().accept()

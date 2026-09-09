"""Application entry point."""

from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import __app_name__
from .ui.assets import icon_path
from .ui.main_window import MainWindow
from .ui.theme import apply_theme


def _icon() -> QIcon:
    path = icon_path()
    return QIcon(path) if path else QIcon()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationDisplayName(__app_name__)
    app.setWindowIcon(_icon())
    apply_theme(app)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

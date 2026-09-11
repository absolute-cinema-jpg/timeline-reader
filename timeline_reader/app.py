"""Application entry point."""

from __future__ import annotations

import sys

from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QWidget

from . import __app_name__
from .ui.assets import icon_path
from .ui.main_window import MainWindow
from .ui.theme import apply_theme


def _icon() -> QIcon:
    path = icon_path()
    return QIcon(path) if path else QIcon()


def _fix_macos_app_name(name: str) -> None:
    """Make the macOS menu-bar / Dock / ⌘-Tab name read *name* instead of
    "Python" when running from source.

    That name comes from the main bundle's ``CFBundleName``. A packaged ``.app``
    supplies it via its Info.plist, but a plain ``python -m`` launch has no
    bundle, so macOS falls back to the interpreter's name. Patching the bundle's
    (mutable) info dictionary before the QApplication is created fixes it. No-op
    off macOS, or if PyObjC isn't installed."""
    if sys.platform != "darwin":
        return
    try:
        from Foundation import NSBundle
    except Exception:
        return
    bundle = NSBundle.mainBundle()
    if bundle is None:
        return
    info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
    if info is not None and info.get("CFBundleName") != name:
        info["CFBundleName"] = name


def install_shortcuts(win: QWidget) -> QShortcut:
    """Close the window with ⌘W. Qt maps 'Ctrl' to the Command key on macOS, so
    'Ctrl+W' is ⌘W there; as the app has a single window and Qt quits when the
    last window closes, ⌘W closes the app. (Explicit rather than the platform
    StandardKey.Close, which resolves to Ctrl+F4 on some platforms.)"""
    shortcut = QShortcut(QKeySequence("Ctrl+W"), win)
    shortcut.activated.connect(win.close)
    return shortcut


def main() -> int:
    _fix_macos_app_name(__app_name__)
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationDisplayName(__app_name__)
    app.setWindowIcon(_icon())
    apply_theme(app)
    win = MainWindow()
    win._close_shortcut = install_shortcuts(win)  # keep a reference alive
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

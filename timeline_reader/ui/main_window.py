"""Main window: branded top bar + page tabs, Resolve-style."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import __app_name__, __version__
from ..columns import CLIPLIST_REPORT, OPTICALS_REPORT
from .assets import icon_path
from .captions_tab import CaptionsTab
from .keynav import KeyNav
from .music_tab import MusicTab
from .report_tab import TimelineReportTab
from .widgets import HelpBanner
from .tagfinder_tab import TagFinderTab


class _TabWidget(QTabWidget):
    """QTabWidget that floats a small button over the right of the tab bar.

    Using the built-in corner widget leaves an unpainted reserved region (a dark
    box) around the button on macOS; overlaying instead keeps the tab bar's own
    full-width background unbroken behind it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._corner_btn: QWidget | None = None

    def set_corner_button(self, btn: QWidget) -> None:
        self._corner_btn = btn
        btn.setParent(self)
        self._place_corner()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_corner()

    def _place_corner(self) -> None:
        btn = self._corner_btn
        if btn is None:
            return
        bar_h = self.tabBar().height() or self.tabBar().sizeHint().height()
        btn.move(self.width() - btn.width() - 14, (bar_h - btn.height()) // 2)
        btn.raise_()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{__app_name__} v{__version__}")
        self.resize(1180, 760)
        self.setMinimumSize(920, 560)

        root = QWidget()
        root.setObjectName("RootView")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._top_bar())

        self.tabs = _TabWidget()
        self.tabs.setDocumentMode(True)

        self.opticals = TimelineReportTab(
            report=OPTICALS_REPORT,
            drop_title="Drop an Avid bin (.avb)",
            drop_sub="Full effect data read straight from the bin",
            export_basename="opticals",
            empty_hint="Load a timeline to build the opticals list",
            count_label="Opticals",
            description=(
                "Lists only clips that carry an <b>Avid effect</b> — resizes, "
                "reframes, 3D warps, timewarps, dissolves and the like — one row "
                "per effect. Plain cuts are left out. Load an <b>Avid bin "
                "(.avb)</b>, which holds the full effect detail. The table works "
                "like All Clips: choose and reorder columns, sort, remove rows, "
                "then export or copy."
            ),
        )
        self.cliplist = TimelineReportTab(
            report=CLIPLIST_REPORT,
            drop_title="Drop an Avid bin (.avb)",
            drop_sub="Every clip on the timeline, across all tracks",
            export_basename="cliplist",
            empty_hint="Load a timeline to build the clip list",
            count_label="Clips",
            description=(
                "Every clip on the timeline — one row per segment, across all "
                "video and audio tracks. Drop an <b>Avid bin (.avb)</b>. Use "
                "<b>Choose columns…</b> to add source metadata (Scene, Take, clip "
                "colour, notes), and drag headers to reorder or click one to sort. "
                "Select rows to export only those, or press <b>Delete</b> to "
                "remove rows you don't want (<b>⌘Z</b> undoes). Export to CSV / "
                "Excel / etc. or copy to the clipboard."
            ),
        )
        self.tagfinder = TagFinderTab()
        self.music = MusicTab()
        self.captions = CaptionsTab()

        for tab in (self.opticals, self.cliplist, self.tagfinder, self.music, self.captions):
            tab.status.connect(self._status)

        # Choosing a timeline file in one tab loads it in the others too. The
        # Captions tab now reads subtitles from the same .avb, so it joins in —
        # it ignores non-bin sources it can't use rather than erroring.
        self._timeline_tabs = (
            self.opticals, self.cliplist, self.tagfinder, self.music, self.captions,
        )
        for tab in self._timeline_tabs:
            tab.drop.fileSelected.connect(
                lambda path, origin=tab: self._sync_timeline_file(origin, path)
            )
            # ...and so does picking a sequence within that file.
            tab.sequenceChanged.connect(
                lambda path, key, origin=tab: self._sync_sequence(origin, path, key)
            )

        self.tabs.addTab(self.cliplist, "  All Clips  ")
        self.tabs.addTab(self.opticals, "  Opticals List  ")
        self.tabs.addTab(self.tagfinder, "  Tag Finder  ")
        self.tabs.addTab(self.music, "  Music Tracker  ")
        self.tabs.addTab(self.captions, "  SRT Generator  ")

        # A single, subtle "i" button on the tab-bar level toggles the current
        # tab's help paragraph.
        self.info_btn = QToolButton()
        self.info_btn.setObjectName("InfoButton")
        self.info_btn.setText("i")
        self.info_btn.setCheckable(True)
        self.info_btn.setFixedSize(20, 20)
        self.info_btn.setCursor(Qt.PointingHandCursor)
        self.info_btn.setToolTip("What does this tab do?")
        self.info_btn.toggled.connect(self._toggle_help)
        self.tabs.set_corner_button(self.info_btn)
        self.tabs.currentChanged.connect(self._sync_info_button)

        outer.addWidget(self.tabs, 1)

        self.setCentralWidget(root)
        self.statusBar().showMessage("Ready")
        self.keynav = KeyNav(self)  # ← → tabs, ↑ ↓ sequences, Enter browse/export
        self._sync_info_button()

    # ---- per-tab help paragraph ------------------------------------------
    def _current_banner(self) -> HelpBanner | None:
        page = self.tabs.currentWidget()
        return page.findChild(HelpBanner) if page else None

    def _toggle_help(self, on: bool):
        banner = self._current_banner()
        if banner is not None:
            banner.set_open(on)

    def _sync_info_button(self, *_):
        """Reflect the current tab's help state in the shared button."""
        banner = self._current_banner()
        self.info_btn.setEnabled(banner is not None)
        self.info_btn.blockSignals(True)
        self.info_btn.setChecked(bool(banner and banner.is_open()))
        self.info_btn.blockSignals(False)

    def _top_bar(self):
        bar = QWidget()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(56)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(12)

        logo = QLabel()
        path = icon_path()
        pix = QPixmap(path) if path else QPixmap()
        if not pix.isNull():
            logo.setPixmap(
                pix.scaled(
                    32,
                    32,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
        else:
            logo.setText("◈")
            logo.setStyleSheet("color:#4a90d9; font-size:22px;")
        lay.addWidget(logo)

        title = QLabel(__app_name__)
        title.setObjectName("AppTitle")
        lay.addWidget(title)

        lay.addStretch(1)
        ver = QLabel(f"v{__version__}")
        ver.setObjectName("AppSubtitle")
        lay.addWidget(ver)
        return bar

    def _sync_timeline_file(self, origin, path: str):
        """Mirror a file chosen in one timeline tab into the other timeline tabs.

        Loading a sibling calls its ``_on_file`` directly (not via its drop
        zone), so it does not re-emit and cannot loop back. A tab already showing
        this file is left alone. Clearing (empty path) is not mirrored.
        """
        if not path:
            return
        mirrored = False
        for tab in self._timeline_tabs:
            if tab is origin:
                continue
            if getattr(tab, "_path", "") != path:
                tab._on_file(path)
                mirrored = True
        if mirrored:
            self._status(f"Loaded {os.path.basename(path)} into every timeline tab")

    def _sync_sequence(self, origin, path: str, key: int):
        """Mirror a sequence picked in one tab into the others, so the choice
        follows the user between tabs. ``set_sequence`` loads directly (not via
        the combo), so siblings don't re-emit and it cannot loop back."""
        for tab in self._timeline_tabs:
            if tab is not origin:
                tab.set_sequence(path, key)

    def _status(self, message: str):
        self.statusBar().showMessage(message, 8000)

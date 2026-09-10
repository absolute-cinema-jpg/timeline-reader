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
    QVBoxLayout,
    QWidget,
)

from .. import __app_name__, __version__
from ..columns import CLIPLIST_REPORT, OPTICALS_REPORT
from .assets import icon_path
from .captions_tab import CaptionsTab
from .markers_tab import MarkersTab
from .music_tab import MusicTab
from .report_tab import TimelineReportTab


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

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        self.opticals = TimelineReportTab(
            report=OPTICALS_REPORT,
            drop_title="Drop a timeline file",
            drop_sub="Avid bin (.avb) gives full effect data · EDL / AAF also accepted",
            export_basename="opticals",
            empty_hint="Load a timeline to build the opticals list",
            count_label="Opticals",
        )
        self.cliplist = TimelineReportTab(
            report=CLIPLIST_REPORT,
            drop_title="Drop a timeline file",
            drop_sub="Avid bin (.avb), EDL, AAF or tab-delimited",
            export_basename="cliplist",
            empty_hint="Load a timeline to build the clip list",
            count_label="Clips",
        )
        self.markers = MarkersTab()
        self.music = MusicTab()
        self.captions = CaptionsTab()

        for tab in (self.opticals, self.cliplist, self.markers, self.music, self.captions):
            tab.status.connect(self._status)

        # Choosing a timeline file in one tab loads it in the others too. The
        # Captions tab reads caption .txt files, not timelines, so it's excluded.
        self._timeline_tabs = (self.opticals, self.cliplist, self.markers, self.music)
        for tab in self._timeline_tabs:
            tab.drop.fileSelected.connect(
                lambda path, origin=tab: self._sync_timeline_file(origin, path)
            )

        self.tabs.addTab(self.opticals, "  Opticals List  ")
        self.tabs.addTab(self.cliplist, "  Clip List  ")
        self.tabs.addTab(self.markers, "  Markers  ")
        self.tabs.addTab(self.music, "  Music Tracker  ")
        self.tabs.addTab(self.captions, "  Captions → SRT  ")
        outer.addWidget(self.tabs, 1)

        self.setCentralWidget(root)
        self.statusBar().showMessage("Ready")

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

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel(__app_name__)
        title.setObjectName("AppTitle")
        sub = QLabel("Media Composer timeline → department reports")
        sub.setObjectName("AppSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(sub)
        lay.addLayout(title_box)

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

    def _status(self, message: str):
        self.statusBar().showMessage(message, 8000)

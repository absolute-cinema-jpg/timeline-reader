"""Main window: branded top bar + page tabs, Resolve-style."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __app_name__, __version__
from ..reports import cliplist_rows, opticals_rows
from .captions_tab import CaptionsTab
from .report_tab import TimelineReportTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{__app_name__}")
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
            report_fn=opticals_rows,
            drop_title="Drop a timeline file",
            drop_sub="Avid bin (.avb) gives full effect data · EDL / AAF also accepted",
            export_basename="opticals",
            empty_hint="Load a timeline to build the opticals list",
        )
        self.cliplist = TimelineReportTab(
            report_fn=cliplist_rows,
            drop_title="Drop a timeline file",
            drop_sub="Avid bin (.avb), EDL, AAF or tab-delimited",
            export_basename="cliplist",
            empty_hint="Load a timeline to build the clip list",
        )
        self.captions = CaptionsTab()

        for tab in (self.opticals, self.cliplist, self.captions):
            tab.status.connect(self._status)

        self.tabs.addTab(self.opticals, "  Opticals List  ")
        self.tabs.addTab(self.cliplist, "  Clip List  ")
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

        logo = QLabel("◈")
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

    def _status(self, message: str):
        self.statusBar().showMessage(message, 8000)

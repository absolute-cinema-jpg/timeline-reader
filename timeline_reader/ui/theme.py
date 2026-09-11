"""DaVinci-Resolve-inspired dark theme.

A single QSS string plus a QPalette. Colours are kept in one place so the whole
app stays consistent. The palette leans on Resolve's neutral graphite greys with
a restrained blue accent and an amber highlight for effect/attention states.
"""

from __future__ import annotations

import os
import tempfile

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QApplication

# --- palette tokens --------------------------------------------------------
BG_APP = "#1a1a1a"        # window background
BG_PANEL = "#232323"      # panels / cards
BG_PANEL_HI = "#2b2b2b"   # raised panel
BG_INPUT = "#2f2f2f"
BORDER = "#3a3a3a"
BORDER_HI = "#4a4a4a"
TEXT = "#d0d0d0"
TEXT_DIM = "#8a8a8a"
TEXT_BRIGHT = "#f0f0f0"
ACCENT = "#4a90d9"        # Resolve-ish blue
ACCENT_HI = "#5fa3e6"
MUTED_BLUE = "#4f7aa8"    # softer, desaturated blue for ticked checkboxes
AMBER = "#e0952b"         # warning highlight
# Accents sampled from the app icon (green button, blue identity columns).
GREEN = "#54b876"         # action green (export)
GREEN_HI = "#63c785"
IDENTITY = "#4c94de"      # # and Clip Name columns (icon blue)
ROW_ALT = "#262626"
HEADER_BG = "#2a2a2a"
SELECT_BG = "#31506f"


_CHECK_PATH: str | None = None


def _checkmark_path() -> str:
    """Path to a white checkmark PNG for ticked checkboxes.

    QSS ``image:`` honours a real file path but not a ``data:`` URI, so we render
    the tick once with QPainter and cache it. Drawn at 2x for a crisp downscale."""
    global _CHECK_PATH
    if _CHECK_PATH and os.path.exists(_CHECK_PATH):
        return _CHECK_PATH
    size = 30
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor("white"))
    pen.setWidthF(3.4)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.drawPolyline(QPolygonF([QPointF(6.5, 15.5), QPointF(12.5, 21.5), QPointF(23.5, 8.5)]))
    p.end()
    path = os.path.join(tempfile.gettempdir(), "tlr_checkmark.png")
    pm.save(path, "PNG")
    _CHECK_PATH = path
    return path


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG_APP))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor(BG_PANEL))
    pal.setColor(QPalette.AlternateBase, QColor(ROW_ALT))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor(BG_PANEL_HI))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor(SELECT_BG))
    pal.setColor(QPalette.HighlightedText, QColor(TEXT_BRIGHT))
    pal.setColor(QPalette.ToolTipBase, QColor(BG_PANEL_HI))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT))
    pal.setColor(QPalette.PlaceholderText, QColor(TEXT_DIM))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor("#5a5a5a"))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#5a5a5a"))
    app.setPalette(pal)
    check_url = _checkmark_path().replace("\\", "/")
    app.setStyleSheet(STYLESHEET.replace("__CHECK_PATH__", check_url))


STYLESHEET = f"""
* {{
    font-family: -apple-system, "SF Pro Text", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
    outline: none;
}}
QWidget {{ color: {TEXT}; background: transparent; }}
QMainWindow, #RootView {{ background: {BG_APP}; }}

/* ---- Top bar / branding ---- */
#TopBar {{
    background: {HEADER_BG};
    border-bottom: 1px solid {BORDER};
}}
#AppTitle {{ color: {TEXT_BRIGHT}; font-size: 15px; font-weight: 600; }}
#AppSubtitle {{ color: {TEXT_DIM}; font-size: 12px; }}

/* ---- Page tabs (Resolve-style pill buttons) ---- */
QTabWidget::pane {{ border: none; background: {BG_APP}; }}
QTabBar {{ background: {HEADER_BG}; qproperty-drawBase: 0; }}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_DIM};
    padding: 9px 20px;
    margin: 6px 3px;
    border: 1px solid transparent;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 500;
}}
QTabBar::tab:hover {{ color: {TEXT}; background: {BG_PANEL_HI}; }}
QTabBar::tab:selected {{
    color: {TEXT_BRIGHT};
    background: {BG_PANEL};
    border: 1px solid {BORDER_HI};
}}

/* ---- Panels / cards ---- */
#Card {{
    background: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
#SectionLabel {{ color: {TEXT_DIM}; font-size: 11px; font-weight: 600; letter-spacing: 1px; }}
#Hint {{ color: {TEXT_DIM}; font-size: 12px; }}
#TabHelp {{
    color: {TEXT}; background: {BG_PANEL};
    border: 1px solid {BORDER}; border-left: 3px solid {ACCENT};
    border-radius: 6px; padding: 10px 12px; font-size: 12px;
}}
#StatBig {{ color: {TEXT_BRIGHT}; font-size: 22px; font-weight: 600; }}
#StatLabel {{ color: {TEXT_DIM}; font-size: 11px; letter-spacing: 0.5px; }}
#WarnLabel {{ color: {AMBER}; font-size: 12px; }}
#FormatBadge {{
    color: {ACCENT_HI}; background: rgba(74,144,217,0.15);
    border: 1px solid rgba(74,144,217,0.4); border-radius: 4px;
    padding: 2px 8px; font-size: 11px; font-weight: 600;
}}

/* ---- Drop zone ---- */
#DropZone {{
    background: {BG_PANEL};
    border: 2px dashed {BORDER_HI};
    border-radius: 10px;
}}
#DropZone[dragActive="true"] {{
    border-color: {ACCENT};
    background: rgba(74,144,217,0.08);
}}
#DropZone[loaded="true"] {{ border-style: solid; border-color: {BORDER}; }}
#DropTitle {{ color: {TEXT}; font-size: 14px; font-weight: 500; }}
#DropSub {{ color: {TEXT_DIM}; font-size: 12px; }}
#DropIcon {{ font-size: 30px; color: {TEXT_DIM}; }}
#DropProgress {{ background: {BORDER}; border: none; border-radius: 2px; }}
#DropProgress::chunk {{ background: {ACCENT}; border-radius: 2px; }}

/* ---- Buttons ---- */
QPushButton {{
    background: {BG_PANEL_HI};
    border: 1px solid {BORDER_HI};
    border-radius: 6px;
    padding: 7px 16px;
    color: {TEXT};
}}
QPushButton:hover {{ background: #333333; border-color: #555; }}
QPushButton:pressed {{ background: #2a2a2a; }}
QPushButton:disabled {{ color: #5a5a5a; border-color: {BORDER}; background: {BG_PANEL}; }}
QPushButton#Primary {{
    background: {GREEN}; border: 1px solid {GREEN};
    color: white; font-weight: 600;
}}
QPushButton#Primary:hover {{ background: {GREEN_HI}; border-color: {GREEN_HI}; }}
QPushButton#Primary:disabled {{ background: #35543f; border-color: #35543f; color: #7f9587; }}

/* ---- Inputs ---- */
QComboBox, QLineEdit, QSpinBox {{
    background: {BG_INPUT};
    border: 1px solid {BORDER_HI};
    border-radius: 5px;
    padding: 5px 8px;
    color: {TEXT};
    min-height: 18px;
}}
QComboBox:hover, QLineEdit:hover {{ border-color: #5a5a5a; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {BG_PANEL_HI};
    border: 1px solid {BORDER_HI};
    selection-background-color: {SELECT_BG};
    color: {TEXT};
}}
QCheckBox {{ color: {TEXT}; spacing: 6px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px; border-radius: 3px;
    border: 1px solid {BORDER_HI}; background: {BG_INPUT};
}}
QCheckBox::indicator:hover {{ border-color: {MUTED_BLUE}; }}
QCheckBox::indicator:checked {{
    background: {MUTED_BLUE}; border-color: {MUTED_BLUE};
    image: url("__CHECK_PATH__");
}}

/* ---- Tables ---- */
QTableView {{
    background: {BG_PANEL};
    alternate-background-color: {ROW_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    gridline-color: {BG_PANEL};
    selection-background-color: {SELECT_BG};
    selection-color: {TEXT_BRIGHT};
}}
QTableView::item {{ padding: 4px 6px; border: none; }}
QHeaderView::section {{
    background: {HEADER_BG};
    color: {TEXT_DIM};
    padding: 7px 8px;
    border: none;
    border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    font-weight: 600;
    font-size: 11px;
}}
QHeaderView::section:hover {{ color: {TEXT}; }}
QTableCornerButton::section {{ background: {HEADER_BG}; border: none; }}

/* ---- Text preview ---- */
QPlainTextEdit, QTextEdit {{
    background: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
    color: {TEXT};
    font-family: "SF Mono", "Menlo", monospace;
    font-size: 12px;
    selection-background-color: {SELECT_BG};
}}

/* ---- Scrollbars ---- */
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #3f3f3f; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #505050; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #3f3f3f; border-radius: 5px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: #505050; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---- Status bar ---- */
QStatusBar {{ background: {HEADER_BG}; color: {TEXT_DIM}; border-top: 1px solid {BORDER}; }}
QStatusBar::item {{ border: none; }}
QToolTip {{ background: {BG_PANEL_HI}; color: {TEXT}; border: 1px solid {BORDER_HI}; padding: 4px; }}
"""

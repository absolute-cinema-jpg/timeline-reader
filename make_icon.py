"""Generate the app icon (assets/icon.png + assets/icon.icns).

Draws a timeline-track motif in the app's palette with QPainter, renders a
1024px master, then emits every macOS iconset size and packs an .icns via
`iconutil`. Run:  ./.venv/bin/python make_icon.py
"""

from __future__ import annotations

import os
import shutil
import subprocess

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QApplication

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

BG_TOP = "#2c3a4d"
BG_BOT = "#161a21"
TRACKS = [
    ("#4a90d9", [(0.00, 0.34), (0.40, 0.62), (0.70, 1.00)]),   # blue
    ("#e0952b", [(0.00, 0.22), (0.30, 0.78), (0.86, 1.00)]),   # amber
    ("#4caf6d", [(0.00, 0.52), (0.60, 1.00)]),                 # green
]
PLAYHEAD = "#e5484d"


def render_master(size: int = 1024) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)

    s = size
    radius = s * 0.225  # macOS squircle-ish rounding

    # Background
    grad = QLinearGradient(0, 0, 0, s)
    grad.setColorAt(0, QColor(BG_TOP))
    grad.setColorAt(1, QColor(BG_BOT))
    p.setBrush(QBrush(grad))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(0, 0, s, s), radius, radius)

    # Inner subtle border for depth
    p.setPen(QPen(QColor(255, 255, 255, 22), s * 0.006))
    p.setBrush(Qt.NoBrush)
    inset = s * 0.02
    p.drawRoundedRect(QRectF(inset, inset, s - 2 * inset, s - 2 * inset),
                      radius - inset, radius - inset)

    # Timeline tracks
    margin_x = s * 0.16
    track_w = s - 2 * margin_x
    n = len(TRACKS)
    track_h = s * 0.13
    gap = s * 0.055
    block_h = n * track_h + (n - 1) * gap
    top = (s - block_h) / 2 + s * 0.03  # nudge down to leave room for playhead knob
    bar_r = track_h * 0.32

    for i, (colour, segments) in enumerate(TRACKS):
        y = top + i * (track_h + gap)
        # track groove
        p.setBrush(QColor(0, 0, 0, 70))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(margin_x, y, track_w, track_h), bar_r, bar_r)
        # clip segments
        base = QColor(colour)
        for j, (a, b) in enumerate(segments):
            seg_pad = track_w * 0.012
            x0 = margin_x + track_w * a + (0 if a == 0 else seg_pad)
            x1 = margin_x + track_w * b - (0 if b == 1.0 else seg_pad)
            seg = QRectF(x0, y, max(0.0, x1 - x0), track_h)
            g = QLinearGradient(0, y, 0, y + track_h)
            g.setColorAt(0, base.lighter(118))
            g.setColorAt(1, base.darker(112))
            p.setBrush(QBrush(g))
            p.drawRoundedRect(seg, bar_r, bar_r)

    # Playhead
    px = margin_x + track_w * 0.52
    p.setPen(QPen(QColor(PLAYHEAD), s * 0.012))
    p.drawLine(QPointF(px, top - s * 0.055), QPointF(px, top + block_h + s * 0.02))
    # playhead knob (triangle)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(PLAYHEAD))
    kh = s * 0.05
    p.drawPolygon(QPolygonF([
        QPointF(px - kh, top - s * 0.055),
        QPointF(px + kh, top - s * 0.055),
        QPointF(px, top - s * 0.005),
    ]))

    p.end()
    return img


def main() -> int:
    app = QApplication.instance() or QApplication([])
    os.makedirs(ASSETS, exist_ok=True)
    master = render_master(1024)
    png_path = os.path.join(ASSETS, "icon.png")
    master.save(png_path)
    print("wrote", png_path)

    iconset = os.path.join(ASSETS, "AppIcon.iconset")
    if os.path.isdir(iconset):
        shutil.rmtree(iconset)
    os.makedirs(iconset)
    sizes = [16, 32, 64, 128, 256, 512, 1024]
    for px in sizes:
        scaled = master.scaled(px, px, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if px in (32, 64, 256, 512, 1024):
            base = px // 2
            scaled.save(os.path.join(iconset, f"icon_{base}x{base}@2x.png"))
        if px in (16, 32, 128, 256, 512):
            scaled.save(os.path.join(iconset, f"icon_{px}x{px}.png"))

    icns_path = os.path.join(ASSETS, "icon.icns")
    if shutil.which("iconutil"):
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns_path], check=True)
        print("wrote", icns_path)
    else:
        print("iconutil not found; left iconset at", iconset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

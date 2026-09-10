"""Avid marker (.txt) export: format, and the per-report name/comment mapping."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from timeline_reader.columns import CLIPLIST_REPORT, OPTICALS_REPORT, ColumnSelection
from timeline_reader.exporters import (
    MARKERS_KIND,
    AvidMarker,
    format_labels,
    index_of_kind,
    write_avid_markers,
)
from timeline_reader.models import Clip, Effect, Timeline


def test_markers_format_listed():
    assert any(".txt" in l and "arker" in l for l in format_labels())
    assert index_of_kind(MARKERS_KIND) == len(format_labels()) - 1


def test_avid_marker_line_layout():
    m = AvidMarker(position=1552, track="V1", colour="Red",
                   name="3D Warp", comment="Scale 145%", duration=1, author="alex")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "m.txt")
        write_avid_markers(p, [m], fps=25.0)
        line = open(p).read().splitlines()[0]
    # author, TC, track, colour, comment, duration, name, colour
    assert line.split("\t") == [
        "alex", "00:01:02:02", "V1", "Red", "Scale 145%", "1", "3D Warp", "Red",
    ]


def _optical_timeline() -> Timeline:
    tl = Timeline(name="seq", fps=25.0, start_tc=90000)  # starts at 01:00:00:00
    clip = Clip(index=1, track="V2", rec_start=100, rec_end=150,
                effects=[Effect(category="Resize", name="Resize", detail="Scale 121%")])
    tl.add(clip)
    return tl


def test_opticals_marker_mapping_and_absolute_tc():
    tl = _optical_timeline()
    ctx = next(OPTICALS_REPORT.iter_ctx(tl))
    m = AvidMarker(
        position=tl.start_tc + ctx.clip.rec_start,
        track=ctx.clip.track,
        colour=OPTICALS_REPORT.marker_colour,
        name=OPTICALS_REPORT.marker_name(ctx),
        comment=OPTICALS_REPORT.marker_comment(ctx),
    )
    assert m.name == "Resize"          # name  = Effect
    assert m.comment == "Scale 121%"   # comment = Notes
    assert m.position == 90100         # absolute: start_tc + rec_start


def test_cliplist_marker_shows_clip_name():
    tl = Timeline(name="seq", fps=25.0)
    tl.add(Clip(index=1, track="V1", clip_name="2-25-3", rec_start=0, rec_end=50))
    ctx = next(CLIPLIST_REPORT.iter_ctx(tl))
    assert CLIPLIST_REPORT.marker_comment(ctx) == "2-25-3"
    assert CLIPLIST_REPORT.marker_name(ctx) == ""


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok  {_name}")
    print("all tests passed")

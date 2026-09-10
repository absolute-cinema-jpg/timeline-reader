"""Avid marker (.txt) export: format, and the per-report name/comment mapping."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from timeline_reader.columns import CLIPLIST_REPORT, OPTICALS_REPORT, ColumnSelection
from timeline_reader.exporters import (
    AVID_MARKER_COLOURS,
    MARKERS_KIND,
    AvidMarker,
    format_labels,
    index_of_kind,
    markers_to_text,
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


def _tracks_at(text: str) -> list[str]:
    return [line.split("\t")[2] for line in text.splitlines()]


def test_same_timecode_markers_staggered_onto_separate_tracks():
    # A dissolve and an animatte landing on the same frame, both on V1.
    markers = [
        AvidMarker(position=1000, track="V1", comment="dissolve"),
        AvidMarker(position=1000, track="V1", comment="animatte"),
        AvidMarker(position=2000, track="V1", comment="lone"),
    ]
    text = markers_to_text(markers, fps=25.0)
    assert _tracks_at(text) == ["V1", "V2", "V1"]  # collision bumps up; lone stays


def test_stagger_preserves_distinct_tracks_and_steps_above_them():
    markers = [
        AvidMarker(position=500, track="V3", comment="a"),
        AvidMarker(position=500, track="V3", comment="b"),
        AvidMarker(position=500, track="V4", comment="c"),
    ]
    # Sorted by track then bumped: V3, then V4 (above V3), then V5 (above V4).
    assert _tracks_at(markers_to_text(markers, fps=25.0)) == ["V3", "V4", "V5"]


def test_colour_override_applies_to_both_colour_columns():
    assert "Green" in AVID_MARKER_COLOURS
    m = AvidMarker(position=100, track="V1", colour="Green", comment="x")
    cols = markers_to_text([m], fps=25.0).split("\t")
    assert cols[3] == "Green" and cols[7].strip() == "Green"


def test_marker_author_defaults_to_app_name():
    from timeline_reader import __app_name__

    m = AvidMarker(position=100, track="V1", colour="Red", comment="x")  # no author
    assert markers_to_text([m], fps=25.0).split("\t")[0] == __app_name__


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

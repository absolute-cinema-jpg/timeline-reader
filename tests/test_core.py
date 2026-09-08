"""Lightweight sanity tests. Run with:  ./.venv/bin/python -m pytest -q
(or plain:  ./.venv/bin/python tests/test_core.py)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from timeline_reader.captions import parse_caption_text, to_srt
from timeline_reader.columns import CLIPLIST_REPORT, ColumnSelection, META_PREFIX
from timeline_reader.effects import classify, is_optical_category
from timeline_reader.models import Clip, Timeline
from timeline_reader.timecode import Timecode


def test_timecode_roundtrip_25():
    tc = Timecode.from_string("11:45:50:01", 25.0)
    assert tc.frames == 1058751
    assert tc.to_string() == "11:45:50:01"


def test_timecode_srt_ms():
    assert Timecode(12, 25.0).to_srt() == "00:00:00,480"
    assert Timecode.from_string("10:00:05:00", 25.0).to_srt() == "10:00:05,000"


def test_effect_classification():
    assert classify("EFF2_BLEND_RESIZE", None) == ("Resize", True)
    assert classify("EFF2_SBLEND", "3DWarp") == ("3D Warp", True)
    assert classify("INT_EFF_SPATIAL_ADAPTER", None)[1] is False
    assert is_optical_category("Timewarp") is True
    assert is_optical_category("Colour Correction") is False


def test_caption_to_srt():
    raw = "<begin subtitles>\n10:00:01:00 10:00:04:12 Hello\nWorld\n<end subtitles>\n"
    doc = parse_caption_text(raw, fps=25.0)
    assert len(doc.cues) == 1
    srt = to_srt(doc)
    assert "10:00:01,000 --> 10:00:04,480" in srt
    assert "Hello\nWorld" in srt


def _demo_timeline() -> Timeline:
    tl = Timeline(name="demo", fps=25.0)
    tl.add(Clip(index=1, track="V1", clip_name="1-1-3", tape_name="A001",
                src_start=100, src_end=150, rec_start=0, rec_end=50,
                meta={"Take": "3", "Scene": "1"}))
    tl.add(Clip(index=2, track="V1", clip_name="2-2-1", tape_name="A002",
                src_start=200, src_end=240, rec_start=50, rec_end=90,
                meta={"Take": "1"}))
    return tl


def test_default_columns_unchanged():
    tl = _demo_timeline()
    sel = ColumnSelection(CLIPLIST_REPORT.key)  # no overrides -> defaults
    headers, rows = CLIPLIST_REPORT.build(tl, sel)
    assert headers == ["#", "Track", "Clip Name", "Tape / Source",
                       "Src In", "Src Out", "Rec In", "Rec Out", "Duration"]
    assert len(rows) == 2


def test_metadata_column_opt_in():
    tl = _demo_timeline()
    assert "Take" in tl.meta_columns and "Scene" in tl.meta_columns
    sel = ColumnSelection(CLIPLIST_REPORT.key)
    sel.set(META_PREFIX + "Take", True)
    headers, rows = CLIPLIST_REPORT.build(tl, sel)
    assert headers[-1] == "Take"
    assert rows[0][-1] == "3" and rows[1][-1] == "1"


def test_exclude_default_column():
    tl = _demo_timeline()
    sel = ColumnSelection(CLIPLIST_REPORT.key)
    sel.set("duration", False)
    headers, _ = CLIPLIST_REPORT.build(tl, sel)
    assert "Duration" not in headers


def test_column_reorder():
    tl = _demo_timeline()
    sel = ColumnSelection(CLIPLIST_REPORT.key)
    sel.set(META_PREFIX + "Take", True)
    # Move Track and Take to the front; the rest keep canonical order after.
    sel.set_order(["track", META_PREFIX + "Take", "index"])
    headers, rows = CLIPLIST_REPORT.build(tl, sel)
    assert headers[:3] == ["Track", "Take", "#"]
    assert headers[3] == "Clip Name"  # unlisted columns stay in canonical order
    assert rows[0][:3] == ["V1", "3", "1"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all tests passed")

"""Lightweight sanity tests. Run with:  ./.venv/bin/python -m pytest -q
(or plain:  ./.venv/bin/python tests/test_core.py)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from timeline_reader.captions import parse_caption_text, to_srt
from timeline_reader.effects import classify, is_optical_category
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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all tests passed")

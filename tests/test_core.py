"""Lightweight sanity tests. Run with:  ./.venv/bin/python -m pytest -q
(or plain:  ./.venv/bin/python tests/test_core.py)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile

from timeline_reader.captions import parse_caption_text, to_srt
from timeline_reader.columns import CLIPLIST_REPORT, ColumnSelection, META_PREFIX
from timeline_reader.effects import classify, is_optical_category
from timeline_reader.exporters import export_table, format_labels
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


def test_caption_decode_encodings():
    # Avid Caption exports may be UTF-8 or UTF-16 (BOM or bare); all must decode.
    from timeline_reader.captions import _decode
    text = "<begin subtitles>\r\n00:00:01:00 00:00:02:00\r\nHi there\r\n"
    for enc in ("utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be"):
        doc = parse_caption_text(_decode(text.encode(enc)), fps=25.0)
        assert len(doc.cues) == 1, f"{enc} decoded to {len(doc.cues)} cues"
        assert doc.cues[0].lines == ["Hi there"]


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
    # Try to move Track and Take ahead of the "#" column; "#" is pinned first
    # regardless, then the listed columns, then the canonical remainder.
    sel.set_order(["track", META_PREFIX + "Take", "index"])
    headers, rows = CLIPLIST_REPORT.build(tl, sel)
    assert headers[:3] == ["#", "Track", "Take"]
    assert headers[3] == "Clip Name"  # unlisted columns stay in canonical order
    assert rows[0][:3] == ["1", "V1", "3"]


def test_marker_extraction():
    """Marker collection resolves absolute position, colour and attributes, and
    de-duplicates locators reached more than once during the track walk.

    Real Avid marker objects aren't in the sample bins, so this exercises the
    extraction with stand-in objects shaped like ``avb.misc.Marker``.
    """
    from timeline_reader.parsers import avb_parser as A

    class FakeMarker:
        def __init__(self, comp_offset, color, attrs):
            self.comp_offset = comp_offset
            self.color = color
            self.attributes = attrs

    class Node:
        property_data: dict = {}

        def __init__(self, attributes):
            self.attributes = attributes

    red = FakeMarker(
        12,
        [90 << 8, 190 << 8, 85 << 8],  # RGB says "Green"...
        {
            "_ATN_CRM_COM": "VFX shot",
            "_ATN_CRM_USER": "alex",
            "_ATN_CRM_COLOR": "Red",  # ...but the named colour is authoritative
            "_ATN_CRM_LENGTH": 5,
        },
    )
    seg = Node({"mark": red})
    tl = Timeline(fps=25.0)
    seen: set = set()
    # Segment starts at record frame 100; marker offset 12 -> absolute 112.
    A._gather_markers(seg, "V1", 100, tl, seen, FakeMarker)
    A._gather_markers(seg, "V1", 100, tl, seen, FakeMarker)  # second pass: no dupes

    assert len(tl.markers) == 1
    m = tl.markers[0]
    assert m.position == 112
    assert m.track == "V1"
    assert m.colour == "Red"  # attribute name wins over the RGB triple
    assert m.comment == "VFX shot"
    assert m.user == "alex"
    assert m.length == 5


def test_marker_extraction_from_sample_bin():
    """End-to-end against the real sample bin's 'markers' sequence, when present.

    The bin lives under the gitignored ``01-test files/``; skip cleanly if absent.
    """
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "01-test files", "bin", "timeline-reader test.avb",
    )
    if not os.path.exists(path):
        return
    from timeline_reader.parsers import parse_timeline
    from timeline_reader.parsers.avb_parser import sequences

    key = next(o.key for o in sequences(path) if o.name == "markers")
    tl = parse_timeline(path, key)
    got = {(m.comment, m.colour, m.track) for m in tl.markers}
    assert ("drama 1", "Red", "V1") in got
    assert ("opticals 1", "Cyan", "V3") in got
    assert ("vfx 1", "White", "V4") in got
    assert len(tl.markers) == 7
    assert all(m.user and m.date for m in tl.markers)


_HEADERS = ["#", "Clip Name", "Rec In"]
_ROWS = [["1", "2-25-3", "00:00:03:17"], ["2", "wide’s", "00:00:05:00"]]


def test_export_formats_listed():
    labels = format_labels()
    assert any(".xlsx" in l for l in labels) and any(".ods" in l for l in labels)


def test_xlsx_roundtrip():
    from openpyxl import load_workbook
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "r.xlsx")
        export_table(path, _HEADERS, _ROWS, "xlsx", sheet_name="THR:test/1")
        ws = load_workbook(path).active
        assert len(ws.title) <= 31 and "/" not in ws.title  # sheet name sanitised
        assert [c.value for c in ws[1]] == _HEADERS
        assert [c.value for c in ws[2]] == _ROWS[0]
        assert ws["B3"].value == "wide’s"  # unicode preserved


def test_ods_roundtrip():
    from odf import teletype
    from odf.opendocument import load
    from odf.table import Table, TableCell, TableRow
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "r.ods")
        export_table(path, _HEADERS, _ROWS, "ods", sheet_name="Report")
        table = load(path).spreadsheet.getElementsByType(Table)[0]
        rows = table.getElementsByType(TableRow)
        header = [teletype.extractText(c) for c in rows[0].getElementsByType(TableCell)]
        assert header == _HEADERS
        assert teletype.extractText(rows[2].getElementsByType(TableCell)[1]) == "wide’s"


def test_settings_roundtrip():
    from PySide6.QtCore import QSettings
    d = tempfile.mkdtemp()
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, d)  # isolate from real prefs
    from timeline_reader import settings as S
    from timeline_reader.exporters import index_of_kind

    S.set_export_format_kind("xlsx")
    assert S.export_format_kind() == "xlsx"
    assert index_of_kind(S.export_format_kind()) == 2

    S.remember_open_path(os.path.join(d, "bin", "seq.avb"))  # dir must exist to be saved
    os.makedirs(os.path.join(d, "bin"), exist_ok=True)
    S.remember_open_path(os.path.join(d, "bin", "seq.avb"))
    assert S.last_open_dir() == os.path.join(d, "bin")

    S.set_caption_fps_index(4)
    assert S.caption_fps_index() == 4


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all tests passed")

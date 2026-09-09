"""Avid DS Caption (.txt) → SubRip (.srt) conversion.

The exact Avid DS caption layout varies by facility, so this parser is written
defensively and will be tightened once a real sample file is provided. It
recognises the common shape: each cue is an in/out timecode pair followed by
one or more text lines, with optional header/footer lines that are ignored.

Cue detection strategies (tried in order):
  1. A line containing two timecodes  -> "IN OUT text…"  (text may follow or be
     on the lines beneath until the next timecode pair / blank line).
  2. Numbered blocks already in SRT-like shape.

Everything is converted through :class:`~timeline_reader.timecode.Timecode`, so
frame-based timecodes become millisecond SRT stamps at the given fps.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .timecode import Timecode

# HH:MM:SS:FF or HH:MM:SS;FF or HH:MM:SS.FF or HH:MM:SS,mmm
_TC = r"\d{1,2}[:;]\d{2}[:;]\d{2}(?:[:;.,]\d{1,3})?"
_TC_RE = re.compile(_TC)
_PAIR_RE = re.compile(rf"^\s*({_TC})\s+({_TC})\s*(.*)$")


@dataclass
class Cue:
    index: int
    start: int              # frames
    end: int                # frames
    lines: list[str] = field(default_factory=list)

    def text(self) -> str:
        return "\n".join(ln for ln in self.lines if ln is not None)


@dataclass
class CaptionDoc:
    fps: float = 25.0
    drop: bool = False
    cues: list[Cue] = field(default_factory=list)
    source_path: str = ""
    warnings: list[str] = field(default_factory=list)


def parse_caption_file(path: str, fps: float = 25.0, drop: bool = False) -> CaptionDoc:
    with open(path, "rb") as fh:
        raw_bytes = fh.read()
    return parse_caption_text(
        _decode(raw_bytes), fps=fps, drop=drop, source_path=path
    )


def _decode(data: bytes) -> str:
    """Decode caption bytes, honouring the byte-order mark.

    Avid's Caption plugin exports either UTF-8 or UTF-16 depending on the
    version/settings, so we detect the encoding rather than assume one — reading
    a UTF-16 file as UTF-8 yields garbage and zero cues.
    """
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")  # BOM selects LE/BE
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig")
    # No BOM: a run of NUL bytes in the head betrays UTF-16.
    if data[:128].count(0) > 8:
        enc = "utf-16-le" if data[1:2] == b"\x00" else "utf-16-be"
        return data.decode(enc, errors="replace")
    return data.decode("utf-8", errors="replace")


def parse_caption_text(raw: str, fps: float = 25.0, drop: bool = False, source_path: str = "") -> CaptionDoc:
    doc = CaptionDoc(fps=fps, drop=drop, source_path=source_path)
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    current: Cue | None = None
    idx = 0
    for line in lines:
        stripped = line.rstrip()
        low = stripped.strip().lower()
        # Skip common header/footer / control markers.
        if not stripped.strip():
            if current is not None:
                current = _finish(current, doc)
            continue
        if low.startswith("<") or low.startswith("@") or low in {
            "begin subtitles", "end subtitles",
        }:
            continue

        m = _PAIR_RE.match(stripped)
        if m:
            if current is not None:
                _finish(current, doc)
            idx += 1
            start = _tc(m.group(1), fps, drop)
            end = _tc(m.group(2), fps, drop)
            current = Cue(index=idx, start=start, end=end)
            trailing = m.group(3).strip()
            if trailing:
                current.lines.append(trailing)
            continue

        if current is not None:
            current.lines.append(stripped.strip())
        # Lines before any timecode pair are treated as header noise.

    if current is not None:
        _finish(current, doc)

    if not doc.cues:
        doc.warnings.append(
            "No caption cues detected. Expected lines of the form "
            "'HH:MM:SS:FF  HH:MM:SS:FF  text'. Share a sample so the parser "
            "can be matched to your exact Avid DS format."
        )
    return doc


def _finish(cue: Cue, doc: CaptionDoc) -> None:
    if cue.lines or cue.end > cue.start:
        doc.cues.append(cue)
    return None


def _tc(text: str, fps: float, drop: bool) -> int:
    text = text.strip()
    if "," in text:  # already millisecond form
        hms, ms = text.rsplit(",", 1)
        h, m, s = hms.split(":")
        total_ms = ((int(h) * 3600 + int(m) * 60 + int(s)) * 1000) + int(ms.ljust(3, "0")[:3])
        return round(total_ms * fps / 1000.0)
    return Timecode.from_string(text, fps, drop).frames


def to_srt(doc: CaptionDoc) -> str:
    """Render a CaptionDoc as SubRip text."""
    blocks = []
    for i, cue in enumerate(doc.cues, 1):
        start = Timecode(cue.start, doc.fps, doc.drop).to_srt()
        end = Timecode(max(cue.end, cue.start), doc.fps, doc.drop).to_srt()
        text = cue.text().strip() or " "
        blocks.append(f"{i}\n{start} --> {end}\n{text}\n")
    return "\n".join(blocks)


def convert_file(path: str, fps: float = 25.0, drop: bool = False) -> tuple[str, CaptionDoc]:
    doc = parse_caption_file(path, fps=fps, drop=drop)
    return to_srt(doc), doc

"""Tab-delimited / CSV parser for Avid bin text exports.

Media Composer's "Export → Tab Delimited" (or a copy-pasted bin view) produces
a table with a header row. Column names vary between projects, so we match them
fuzzily onto our model fields. Timecode columns are detected by header name.
"""

from __future__ import annotations

import csv
import os

from ..models import Clip, Effect, Timeline
from ..timecode import Timecode
from . import ParseError

# Candidate header names (lower-cased, punctuation-stripped) per field.
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "clip_name": ("name", "clip name", "clip", "title"),
    "tape_name": ("tape", "tape name", "source file", "source name", "reel", "camroll", "camera roll"),
    "track": ("track", "v track", "video track"),
    "src_start": ("start", "source start", "src start", "mark in", "soft in"),
    "src_end": ("end", "source end", "src end", "mark out", "soft out"),
    "rec_start": ("rec start", "record in", "timeline in", "ti", "master start"),
    "rec_end": ("rec end", "record out", "timeline out", "to", "master end"),
    "duration": ("duration", "dur", "length"),
    "effects": ("effect", "effects", "fx"),
}


def _norm(s: str) -> str:
    return " ".join(s.strip().lower().replace("_", " ").split())


def parse(path: str) -> Timeline:
    with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        delim = "\t" if sample.count("\t") >= sample.count(",") else ","
        reader = csv.reader(fh, delimiter=delim)
        rows = [r for r in reader if any(cell.strip() for cell in r)]

    if len(rows) < 2:
        raise ParseError("File has no data rows below a header.")

    raw_header = [h.strip() for h in rows[0]]
    header = [_norm(h) for h in rows[0]]
    colmap = _map_columns(header)
    mapped_idxs = set(colmap.values())
    # Any column we didn't map to a known field becomes a metadata column.
    extra_cols = [
        (idx, raw_header[idx] or f"Column {idx + 1}")
        for idx in range(len(raw_header))
        if idx not in mapped_idxs
    ]
    if "clip_name" not in colmap and "tape_name" not in colmap:
        raise ParseError(
            "Couldn't find a clip-name or tape column in the header. "
            "Export from Avid as Tab Delimited with column headings."
        )

    tl = Timeline(
        name=os.path.splitext(os.path.basename(path))[0],
        source_path=path,
        source_format="Tab-delimited",
        fps=25.0,
    )
    for i, row in enumerate(rows[1:], 1):
        def cell(field: str) -> str:
            idx = colmap.get(field)
            return row[idx].strip() if idx is not None and idx < len(row) else ""

        clip = Clip(
            index=i,
            track=cell("track") or "V1",
            clip_name=cell("clip_name"),
            tape_name=cell("tape_name"),
            fps=tl.fps,
        )
        _set_tc(clip, "src_start", cell("src_start"), tl.fps)
        _set_tc(clip, "src_end", cell("src_end"), tl.fps)
        _set_tc(clip, "rec_start", cell("rec_start"), tl.fps)
        _set_tc(clip, "rec_end", cell("rec_end"), tl.fps)
        if clip.src_end <= clip.src_start:
            dur = cell("duration")
            if dur:
                _set_tc(clip, "src_end", None, tl.fps, base=clip.src_start, dur=dur)
        fx = cell("effects")
        if fx:
            clip.effects.append(Effect(category=fx, name=fx))
        for idx, label in extra_cols:
            if idx < len(row):
                val = row[idx].strip()
                if val:
                    clip.meta[label] = val
        if clip.clip_name or clip.tape_name:
            tl.add(clip)

    if not tl.clips:
        raise ParseError("No usable rows found in the tab-delimited file.")
    return tl


def _map_columns(header: list[str]) -> dict[str, int]:
    colmap: dict[str, int] = {}
    for field, aliases in _FIELD_ALIASES.items():
        for idx, name in enumerate(header):
            if name in aliases:
                colmap[field] = idx
                break
        else:
            for idx, name in enumerate(header):
                if any(name == a or name.startswith(a) for a in aliases):
                    colmap.setdefault(field, idx)
                    break
    return colmap


def _set_tc(clip: Clip, field: str, text: str | None, fps: float, base: int = 0, dur: str | None = None) -> None:
    try:
        if dur is not None:
            frames = base + Timecode.from_string(dur, fps).frames
        elif text:
            frames = Timecode.from_string(text, fps).frames
        else:
            return
    except ValueError:
        return
    setattr(clip, field, frames)

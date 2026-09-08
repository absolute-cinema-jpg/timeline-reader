"""Report builders: turn a :class:`Timeline` into tabular rows.

Each report returns ``(headers, rows)`` where rows are lists of strings, ready
for a table widget or a CSV/TSV writer. This keeps the UI and the exporter
sharing one source of truth for column order and formatting.
"""

from __future__ import annotations

from .effects import is_optical_category
from .models import Timeline
from .timecode import frames_to_tc, frames_to_duration

OPTICALS_HEADERS = [
    "#", "Track", "Effect", "Type", "Clip Name", "Tape / Source",
    "Rec In", "Rec Out", "Src In", "Src Out", "Duration", "Notes",
]

CLIPLIST_HEADERS = [
    "#", "Track", "Clip Name", "Tape / Source",
    "Src In", "Src Out", "Rec In", "Rec Out", "Duration",
]


def opticals_rows(tl: Timeline) -> tuple[list[str], list[list[str]]]:
    """One row per optical effect, in record order."""
    rows: list[list[str]] = []
    n = 0
    for clip in tl.sorted_by_record():
        for eff in clip.effects:
            if not is_optical_category(eff.category):
                continue
            n += 1
            rows.append([
                str(n),
                clip.track,
                eff.category,
                eff.name,
                clip.clip_name,
                clip.tape_name,
                frames_to_tc(clip.rec_start, tl.fps, tl.drop),
                frames_to_tc(clip.rec_end, tl.fps, tl.drop),
                frames_to_tc(clip.src_start, tl.fps, tl.drop),
                frames_to_tc(clip.src_end, tl.fps, tl.drop),
                frames_to_duration(clip.duration, tl.fps),
                eff.detail,
            ])
    return OPTICALS_HEADERS, rows


def cliplist_rows(tl: Timeline) -> tuple[list[str], list[list[str]]]:
    """One row per clip, in record order."""
    rows: list[list[str]] = []
    for clip in tl.sorted_by_record():
        rows.append([
            str(clip.index),
            clip.track,
            clip.clip_name,
            clip.tape_name,
            frames_to_tc(clip.src_start, tl.fps, tl.drop),
            frames_to_tc(clip.src_end, tl.fps, tl.drop),
            frames_to_tc(clip.rec_start, tl.fps, tl.drop),
            frames_to_tc(clip.rec_end, tl.fps, tl.drop),
            frames_to_duration(clip.duration, tl.fps),
        ])
    return CLIPLIST_HEADERS, rows

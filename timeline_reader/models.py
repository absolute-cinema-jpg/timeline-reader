"""Data model shared by every parser and every report/exporter.

Parsers turn a source file into a :class:`Timeline`. Reports read a
:class:`Timeline` and produce rows for a table / spreadsheet. Keeping this
layer format-agnostic is what lets the UI treat an EDL, an AAF and an Avid
bin identically once loaded.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SequenceOption:
    """One selectable sequence within a multi-sequence source (bin / AAF)."""

    key: int                # stable ordinal into the parser's candidate list
    name: str
    detail: str = ""        # e.g. "8 video tracks · 00:12:12:16"


@dataclass
class Effect:
    """A single clip effect discovered on the timeline."""

    category: str          # normalised bucket: "Resize", "3D Warp", "Timewarp", ...
    name: str              # human effect name from the source ("3DWarp", "Resize")
    effect_id: str = ""    # raw Avid effect id / plugin id
    detail: str = ""       # extra info, e.g. speed "50%" or "Freeze frame"


@dataclass
class Marker:
    """A timeline locator (marker) placed on a track at a record position."""

    position: int                    # absolute record position, frames
    track: str = ""                  # "V1", "A1", ...
    comment: str = ""                # locator comment text
    colour: str = ""                 # nearest Avid colour name (e.g. "Red")
    user: str = ""                   # who created it, if recorded
    date: str = ""                   # creation date, if recorded
    length: int = 0                  # marker span in frames (0 = point marker)


@dataclass
class Clip:
    """One clip event on the timeline (a segment on a single track)."""

    index: int                       # 1-based order within the whole timeline
    track: str                       # "V1", "V2", ...
    clip_name: str = ""              # editor-facing name (FROM CLIP NAME)
    tape_name: str = ""              # source tape / camera roll / file
    master_name: str = ""            # master clip name (the song, for music cues)
    note: str = ""                   # timeline clip note (segment _COMMENT)
    src_start: int = 0               # source in, frames
    src_end: int = 0                 # source out (exclusive), frames
    rec_start: int = 0               # record in, frames
    rec_end: int = 0                 # record out (exclusive), frames
    fps: float = 25.0
    drop: bool = False
    effects: list[Effect] = field(default_factory=list)
    meta: dict[str, str] = field(default_factory=dict)  # extra metadata columns
    head_transition: int = 0         # incoming dissolve length, frames (audio cues)
    tail_transition: int = 0         # outgoing dissolve length, frames (audio cues)
    muted: bool = False              # clip sits on a muted (audio-mixer) track
    is_transition: bool = False      # a transition (dissolve / morph cut), not a clip

    @property
    def duration(self) -> int:
        return max(0, self.rec_end - self.rec_start)


@dataclass
class Timeline:
    """A parsed sequence plus provenance about where it came from."""

    name: str = ""
    fps: float = 25.0
    drop: bool = False
    clips: list[Clip] = field(default_factory=list)
    audio_clips: list[Clip] = field(default_factory=list)  # sound-track segments
    start_tc: int = 0                # sequence record start timecode, frames
    markers: list[Marker] = field(default_factory=list)
    source_path: str = ""
    source_format: str = ""          # "Avid Bin", "EDL", "AAF", "Tab-delimited"
    warnings: list[str] = field(default_factory=list)
    available_sequences: list["SequenceOption"] = field(default_factory=list)
    sequence_key: int | None = None  # which option this timeline was parsed from
    meta_columns: list[str] = field(default_factory=list)  # discovered metadata keys, ordered

    def add(self, clip: Clip) -> None:
        self.clips.append(clip)
        for key in clip.meta:
            if key not in self.meta_columns:
                self.meta_columns.append(key)

    def sorted_by_record(self) -> list[Clip]:
        """Clips in record order (then by track), re-indexed 1..N."""
        ordered = sorted(self.clips, key=lambda c: (c.rec_start, c.track))
        for i, c in enumerate(ordered, 1):
            c.index = i
        return ordered

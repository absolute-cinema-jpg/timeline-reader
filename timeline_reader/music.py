"""Music Tracker: merge a timeline's music segments into cues.

The Music Tracker reports one row per *music cue* — a single piece of music as
it plays out over the cut, not the many individual segments an editor leaves
behind. Editors constantly chop a music track up (add edits, nudging a clip a
few seconds along, checkerboarding a cue across two tracks so it can cross over
itself) and none of that should split a cue.

Given the sound tracks the user has designated as music (they are expected to
have moved every music clip onto those tracks and cleared everything else off
them beforehand), this module:

* gathers every audio segment on those tracks across the whole timeline,
* works out each segment's record in/out, optionally extending them to cover a
  cross dissolve on the head/tail,
* and sweeps them in record order, merging consecutive segments of the *same*
  source into one cue. A cue ends only when it falls silent for longer than a
  user-set gap (default one second), or when a different piece of music
  interrupts it.

Muted clips (clips on a track muted in the audio mixer — Avid records mute per
track, not per clip) are dropped by default; they can be kept, and then a Muted
column flags them.

Columns are configurable exactly like the Opticals / Clip List reports, via the
shared :class:`~timeline_reader.columns.ColumnSelection`. The reel is read from
the hour field of the cue's record in-point (a sequence that starts at
01:00:00:00 is reel 1), which is why the parser carries the sequence's start
timecode.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .columns import ColumnDef, ColumnSelection
from .models import Clip, Timeline
from .timecode import frames_to_duration, frames_to_tc

# Bin metadata keys, best first. Avid truncates some ID3-derived column names
# (e.g. the description field), so these match the real, truncated keys.
_ARTIST_KEYS = (
    "Lead performer(s)/Soloist(s)",
    "Composer",
    "Artist",
    "Band/Orchestra/Accompaniment",
    "Original artist(s)/performer(s)",
)
_TITLE_KEYS = (
    "Title/songname/content descripti",
    "Title",
    "Song",
)
_ALBUM_KEYS = (
    "Album/Movie/Show title",
    "Album",
)

REPORT_KEY = "music"
DEFAULT_GAP_SECONDS = 1.0


@dataclass
class MusicCue:
    """One merged music cue, spanning one or more segments and tracks."""

    song: str                        # merge identity (Avid clip / master name)
    title: str                       # song name (the "Track" column)
    album: str
    artist: str
    filename: str                    # media file name (with extension where known)
    tracks: list[str]                # every audio track the cue touches, in order
    rec_in: int                      # absolute record in, frames (incl. start TC)
    rec_out: int                     # absolute record out, frames
    muted: bool = False              # every segment of the cue is on a muted track
    fps: float = 25.0
    drop: bool = False

    @property
    def duration(self) -> int:
        return max(0, self.rec_out - self.rec_in)

    def reel(self) -> str:
        """Reel number = the hour field of the record in-point."""
        hh = frames_to_tc(self.rec_in, self.fps, self.drop)[:2]
        try:
            return str(int(hh))
        except ValueError:
            return ""


# --------------------------------------------------------------------------- #
# Columns (configurable, persisted — shares ColumnSelection with the reports)
# --------------------------------------------------------------------------- #
def _columns(include_muted: bool) -> list[ColumnDef]:
    cols = [
        ColumnDef("reel", "Reel", "Core", True, lambda c: c.reel()),
        ColumnDef("track", "Track", "Core", True, lambda c: c.title),
        ColumnDef("artist", "Artist / Composer", "Core", True, lambda c: c.artist),
        ColumnDef("album", "Album", "Core", True, lambda c: c.album),
        ColumnDef("filename", "Filename", "Core", True, lambda c: c.filename),
        ColumnDef("tc_in", "TC In", "Timecode", True,
                  lambda c: frames_to_tc(c.rec_in, c.fps, c.drop)),
        ColumnDef("tc_out", "TC Out", "Timecode", True,
                  lambda c: frames_to_tc(c.rec_out, c.fps, c.drop)),
        ColumnDef("duration", "Duration", "Timecode", True,
                  lambda c: frames_to_duration(c.duration, c.fps)),
        ColumnDef("audio_track", "Audio Track", "Extra", False,
                  lambda c: ", ".join(c.tracks)),
    ]
    if include_muted:
        # Only offered (and defaulted on) when muted clips are being included.
        cols.append(
            ColumnDef("muted", "Muted", "Core", True, lambda c: "Muted" if c.muted else "")
        )
    return cols


def all_columns(include_muted: bool = False) -> list[ColumnDef]:
    """Every column the Music Tracker can show (for the column chooser)."""
    return _columns(include_muted)


# Default column labels, shown as the empty table's header row before a load.
HEADERS_HINT = [c.label for c in _columns(False) if c.default]


def render(
    cues: list["MusicCue"], selection: ColumnSelection, include_muted: bool = False
) -> tuple[list[ColumnDef], list[list[str]]]:
    """Ordered, included column defs plus the data rows for a list of cues."""
    cols = selection.ordered(
        [c for c in _columns(include_muted) if selection.effective(c)]
    )
    rows = [[col.getter(cue) for col in cols] for cue in cues]
    return cols, rows


# --------------------------------------------------------------------------- #
# Cue building
# --------------------------------------------------------------------------- #
def _meta_of(clip: Clip, keys) -> str:
    for key in keys:
        val = clip.meta.get(key, "").strip()
        if val:
            return val
    return ""


def _identity(clip: Clip) -> str:
    """What makes two segments "the same piece of music" — the master clip name.

    Not the deepest source name: the mob chain frequently bottoms out in a name
    shared by many unrelated clips (a tape roll, or Avid's "Signature Source Mob"
    for rendered / consolidated / mixdown audio). Using that would fuse two
    different songs cut back to back into one cue, and the second would vanish."""
    return clip.master_name or clip.clip_name or clip.tape_name or ""


def _filename(clip: Clip) -> str:
    """The media file name: the first name in the chain that looks like a file
    (has an extension), else the master clip name."""
    for name in (clip.tape_name, clip.master_name, clip.clip_name):
        if name and "." in name:
            return name
    return clip.master_name or clip.tape_name or clip.clip_name


def _track_index(name: str) -> int:
    """Sort key for a track name like ``A5`` (numeric where possible)."""
    digits = "".join(ch for ch in name if ch.isdigit())
    return int(digits) if digits else 0


def available_tracks(tl: Timeline) -> list[str]:
    """Sound tracks that actually carry audio, ordered A1, A2, … — the choices
    the user picks their music tracks from."""
    names = {c.track for c in tl.audio_clips}
    return sorted(names, key=_track_index)


def _segment_bounds(clip: Clip, include_dissolves: bool) -> tuple[int, int]:
    """A segment's record in/out. With dissolves included, the in-point already
    sits at the start of the head fade (the clip was pulled back under it) and the
    out-point is pushed past the cut to the end of the tail fade; excluded, the
    fades are trimmed off so the bounds are the hard cut points."""
    if include_dissolves:
        return clip.rec_start, clip.rec_end + clip.tail_transition
    return clip.rec_start + clip.head_transition, clip.rec_end


def build_cues(
    tl: Timeline,
    tracks,
    gap_seconds: float = DEFAULT_GAP_SECONDS,
    include_dissolves: bool = True,
    include_muted: bool = False,
) -> list[MusicCue]:
    """Merge the audio segments on the chosen *tracks* into music cues.

    *tracks* is the set/list of track names (e.g. ``{"A5", "A6"}``) the user has
    designated as music. Segments are merged across every chosen track at once,
    so a cue checkerboarded over two tracks stays a single cue. Muted clips are
    dropped unless *include_muted*; a cue is flagged muted only when every one of
    its segments is muted.
    """
    chosen = set(tracks)
    gap = max(0, round(gap_seconds * tl.fps))

    segs = []
    for clip in tl.audio_clips:
        if clip.track not in chosen:
            continue
        if clip.muted and not include_muted:
            continue
        s_in, s_out = _segment_bounds(clip, include_dissolves)
        segs.append((clip, s_in, s_out))
    # Record order; ties broken by track so a deterministic segment opens a cue.
    segs.sort(key=lambda s: (s[1], _track_index(s[0].track)))

    cues: list[MusicCue] = []
    cur: MusicCue | None = None
    cur_id = ""
    for clip, s_in, s_out in segs:
        ident = _identity(clip)
        if cur is not None and ident == cur_id and s_in <= cur.rec_out + gap:
            # Same piece of music, no long gap -> extend the open cue.
            cur.rec_out = max(cur.rec_out, s_out)
            if clip.track not in cur.tracks:
                cur.tracks.append(clip.track)
            cur.muted = cur.muted and clip.muted  # muted only if all segments are
            if not cur.artist:
                cur.artist = _meta_of(clip, _ARTIST_KEYS)
            if not cur.album:
                cur.album = _meta_of(clip, _ALBUM_KEYS)
        else:
            cur = MusicCue(
                song=ident,
                title=_meta_of(clip, _TITLE_KEYS) or ident,
                album=_meta_of(clip, _ALBUM_KEYS),
                artist=_meta_of(clip, _ARTIST_KEYS),
                filename=_filename(clip),
                tracks=[clip.track],
                rec_in=tl.start_tc + s_in,
                rec_out=tl.start_tc + s_out,
                muted=clip.muted,
                fps=tl.fps,
                drop=tl.drop,
            )
            cur_id = ident
            cues.append(cur)

    for cue in cues:
        cue.tracks.sort(key=_track_index)
    return cues


def build_rows(
    tl: Timeline,
    tracks,
    selection: ColumnSelection,
    gap_seconds: float = DEFAULT_GAP_SECONDS,
    include_dissolves: bool = True,
    include_muted: bool = False,
) -> tuple[list[MusicCue], list[ColumnDef], list[list[str]]]:
    """Cues, the ordered column defs, and the data rows — everything the tab needs
    (the cues carry per-row durations for the selection-aware stats)."""
    cues = build_cues(tl, tracks, gap_seconds, include_dissolves, include_muted)
    cols, rows = render(cues, selection, include_muted)
    return cues, cols, rows

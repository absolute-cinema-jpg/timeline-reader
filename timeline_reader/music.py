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

The reel is read from the hour field of the cue's record in-point (a sequence
that starts at 01:00:00:00 is reel 1), which is why the parser carries the
sequence's start timecode.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Clip, Timeline
from .timecode import frames_to_duration, frames_to_tc

# Bin metadata keys that carry the artist / composer, best first. Avid truncates
# some ID3-derived column names (e.g. the description field), so match leniently.
_ARTIST_KEYS = (
    "Lead performer(s)/Soloist(s)",
    "Composer",
    "Artist",
    "Band/Orchestra/Accompaniment",
    "Original artist(s)/performer(s)",
)

HEADERS = ["Reel", "Track", "Artist / Composer", "Filename", "TC In", "TC Out", "Duration"]

DEFAULT_GAP_SECONDS = 1.0


@dataclass
class MusicCue:
    """One merged music cue, spanning one or more segments and tracks."""

    song: str                        # identity (Avid clip / master name)
    filename: str                    # media file name (with extension where known)
    artist: str
    tracks: list[str]                # every track the cue touches, in order
    rec_in: int                      # absolute record in, frames (incl. start TC)
    rec_out: int                     # absolute record out, frames
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

    def row(self) -> list[str]:
        return [
            self.reel(),
            ", ".join(self.tracks),
            self.artist,
            self.filename,
            frames_to_tc(self.rec_in, self.fps, self.drop),
            frames_to_tc(self.rec_out, self.fps, self.drop),
            frames_to_duration(self.duration, self.fps),
        ]


def _artist_of(clip: Clip) -> str:
    for key in _ARTIST_KEYS:
        val = clip.meta.get(key, "").strip()
        if val:
            return val
    return ""


def _identity(clip: Clip) -> str:
    """What makes two segments "the same piece of music" — the source name."""
    return clip.clip_name or clip.tape_name or ""


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
) -> list[MusicCue]:
    """Merge the audio segments on the chosen *tracks* into music cues.

    *tracks* is the set/list of track names (e.g. ``{"A5", "A6"}``) the user has
    designated as music. Segments are merged across every chosen track at once,
    so a cue checkerboarded over two tracks stays a single cue.
    """
    chosen = set(tracks)
    gap = max(0, round(gap_seconds * tl.fps))

    segs = [
        (clip, *_segment_bounds(clip, include_dissolves))
        for clip in tl.audio_clips
        if clip.track in chosen
    ]
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
            if not cur.artist:
                cur.artist = _artist_of(clip)
        else:
            cur = MusicCue(
                song=ident,
                filename=clip.tape_name or clip.clip_name,
                artist=_artist_of(clip),
                tracks=[clip.track],
                rec_in=tl.start_tc + s_in,
                rec_out=tl.start_tc + s_out,
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
    gap_seconds: float = DEFAULT_GAP_SECONDS,
    include_dissolves: bool = True,
) -> tuple[list[MusicCue], list[list[str]]]:
    """Cues plus their table rows (the tab needs the cues for per-row durations)."""
    cues = build_cues(tl, tracks, gap_seconds, include_dissolves)
    return cues, [c.row() for c in cues]

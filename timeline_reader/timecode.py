"""Frame-accurate timecode handling.

Media Composer projects are frame-based. Internally we always carry positions
as integer frame counts and only format to a timecode string at the edges.
Drop-frame is supported for the 29.97 / 59.94 families; everything else is
treated as non-drop.
"""

from __future__ import annotations

from dataclasses import dataclass

# Frame rates that use SMPTE drop-frame counting when the project is DF.
_DROP_FRAME_RATES = {30: 2, 60: 4}  # nominal fps -> frames dropped per minute


def _nominal_fps(fps: float) -> int:
    """Round a real frame rate (e.g. 29.97) to its nominal integer (30)."""
    return int(round(fps))


@dataclass(frozen=True)
class Timecode:
    """A timecode position expressed as an integer frame count at a given rate."""

    frames: int
    fps: float = 25.0
    drop: bool = False

    # ---- construction -----------------------------------------------------
    @classmethod
    def from_string(cls, text: str, fps: float = 25.0, drop: bool | None = None) -> "Timecode":
        """Parse ``HH:MM:SS:FF`` (``;`` before frames signals drop-frame)."""
        text = text.strip()
        if not text:
            return cls(0, fps, bool(drop))
        sep_drop = ";" in text or "." in text
        norm = text.replace(";", ":").replace(".", ":")
        parts = norm.split(":")
        if len(parts) != 4:
            raise ValueError(f"Not a timecode: {text!r}")
        hh, mm, ss, ff = (int(p) for p in parts)
        is_drop = sep_drop if drop is None else drop
        frames = cls._hmsf_to_frames(hh, mm, ss, ff, fps, is_drop)
        return cls(frames, fps, is_drop)

    # ---- conversion helpers ----------------------------------------------
    @staticmethod
    def _hmsf_to_frames(hh: int, mm: int, ss: int, ff: int, fps: float, drop: bool) -> int:
        nominal = _nominal_fps(fps)
        total_minutes = hh * 60 + mm
        frames = ((hh * 3600 + mm * 60 + ss) * nominal) + ff
        if drop and nominal in _DROP_FRAME_RATES:
            dropped = _DROP_FRAME_RATES[nominal]
            # Two frames (or four) dropped each minute except every tenth minute.
            frames -= dropped * (total_minutes - total_minutes // 10)
        return frames

    def to_string(self) -> str:
        nominal = _nominal_fps(self.fps)
        f = self.frames
        if self.drop and nominal in _DROP_FRAME_RATES:
            dropped = _DROP_FRAME_RATES[nominal]
            frames_per_min = nominal * 60
            frames_per_10min = frames_per_min * 10 - dropped * 9
            d, m = divmod(f, frames_per_10min)
            if m < dropped:
                m += dropped
            f += dropped * 9 * d + dropped * ((m - dropped) // (frames_per_min - dropped))
        ff = f % nominal
        secs = f // nominal
        ss = secs % 60
        mm = (secs // 60) % 60
        hh = (secs // 3600) % 24
        sep = ";" if (self.drop and nominal in _DROP_FRAME_RATES) else ":"
        return f"{hh:02d}:{mm:02d}:{ss:02d}{sep}{ff:02d}"

    def to_srt(self) -> str:
        """``HH:MM:SS,mmm`` for SubRip, derived from real (not nominal) fps."""
        total_ms = round(self.frames * 1000.0 / self.fps)
        ms = total_ms % 1000
        secs = total_ms // 1000
        return f"{secs // 3600:02d}:{(secs // 60) % 60:02d}:{secs % 60:02d},{ms:03d}"

    # ---- arithmetic -------------------------------------------------------
    def __add__(self, frames: int) -> "Timecode":
        return Timecode(self.frames + int(frames), self.fps, self.drop)

    def __sub__(self, other) -> "Timecode":
        if isinstance(other, Timecode):
            return Timecode(self.frames - other.frames, self.fps, self.drop)
        return Timecode(self.frames - int(other), self.fps, self.drop)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.to_string()


def frames_to_tc(frames: int, fps: float = 25.0, drop: bool = False) -> str:
    return Timecode(int(frames), fps, drop).to_string()


def frames_to_duration(frames: int, fps: float = 25.0) -> str:
    """Human duration string for a frame count (used for effect lengths)."""
    return Timecode(int(frames), fps, False).to_string()

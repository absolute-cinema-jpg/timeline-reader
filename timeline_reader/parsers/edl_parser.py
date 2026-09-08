"""CMX3600 EDL parser.

Handles the dialect Media Composer exports: ``TITLE`` / ``FCM`` headers, event
lines, ``*FROM CLIP NAME`` / ``*TO CLIP NAME`` comments, ``M2`` motion-memory
lines (speed ramps / freezes) and ``** FREEZE FRAME`` markers. Transitions with
a dissolve/wipe duration field are tolerated.
"""

from __future__ import annotations

import os
import re

from ..effects import classify
from ..models import Clip, Effect, Timeline
from ..timecode import Timecode
from . import ParseError

_TC = r"\d{1,2}[:;.]\d{2}[:;.]\d{2}[:;.]\d{2}"
_EVENT_RE = re.compile(r"^(\d{1,6})\s+(.*)$")
_TC_RE = re.compile(_TC)
_FROM_RE = re.compile(r"^\*\s*FROM CLIP NAME:\s*(.*)$", re.I)
_M2_RE = re.compile(r"^M2\s+(\S+)\s+(-?\d+\.?\d*)\s+(" + _TC + r")", re.I)


def parse(path: str) -> Timeline:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()

    tl = Timeline(
        name=os.path.splitext(os.path.basename(path))[0],
        source_path=path,
        source_format="EDL",
        fps=25.0,
    )
    drop = False
    fps = 25.0
    saw_header = False
    # Track guess from the filename tail (…-V2-opticals -> V2) else channel.
    file_track = _track_from_filename(path)

    current: Clip | None = None
    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        upper = line.strip().upper()

        if upper.startswith("TITLE:"):
            tl.name = line.split(":", 1)[1].strip() or tl.name
            saw_header = True
            continue
        if upper.startswith("FCM:"):
            drop = "DROP" in upper and "NON" not in upper
            tl.drop = drop
            saw_header = True
            continue

        m2 = _M2_RE.match(line.strip())
        if m2 and current is not None:
            _apply_motion(current, float(m2.group(2)))
            continue

        if line.lstrip().startswith("*") or line.lstrip().startswith("**"):
            fm = _FROM_RE.match(line.strip())
            if fm and current is not None and not current.clip_name:
                current.clip_name = fm.group(1).strip()
            elif "FREEZE FRAME" in upper and current is not None:
                _add_effect(current, "Motion Effect", "Freeze Frame", detail="Freeze frame")
            continue

        ev = _EVENT_RE.match(line)
        if not ev:
            continue
        clip = _parse_event(ev, fps, drop, file_track)
        if clip is None:
            continue
        clip.index = len(tl.clips) + 1
        tl.add(clip)
        current = clip

    if not tl.clips:
        if saw_header:
            tl.warnings.append("This EDL has no edit events (empty track).")
            return tl
        raise ParseError("No EDL events found — is this a CMX3600 EDL?")
    return tl


def _parse_event(ev: re.Match, fps: float, drop: bool, file_track: str) -> Clip | None:
    event_no, rest = ev.group(1), ev.group(2)
    tokens = rest.split()
    tcs = [t for t in tokens if _TC_RE.fullmatch(t)]
    if len(tcs) < 4:
        return None
    src_in, src_out, rec_in, rec_out = (
        Timecode.from_string(t, fps, drop) for t in tcs[-4:]
    )
    # Everything before the timecodes: reel, channel, transition, [dur].
    head = tokens[: len(tokens) - 4]
    reel = head[0] if head else ""
    channel = head[1] if len(head) > 1 else "V"
    transition = head[2] if len(head) > 2 else "C"

    track = file_track or _channel_to_track(channel)
    clip = Clip(
        index=0,
        track=track,
        tape_name=reel,
        src_start=src_in.frames,
        src_end=src_out.frames,
        rec_start=rec_in.frames,
        rec_end=rec_out.frames,
        fps=fps,
        drop=drop,
    )
    if transition and transition.upper().startswith(("D", "W")) and transition.upper() != "C":
        kind = "Dissolve" if transition.upper().startswith("D") else "Wipe"
        _add_effect(clip, kind, transition, effect_id=transition)
    return clip


def _apply_motion(clip: Clip, speed: float) -> None:
    if abs(speed) < 0.001:
        detail = "Freeze frame"
    else:
        detail = f"{speed:g}%" + (" (reverse)" if speed < 0 else "")
    _add_effect(clip, "Timewarp", "Motion Memory", detail=detail)


def _add_effect(clip: Clip, category: str, name: str, effect_id: str = "", detail: str = "") -> None:
    clip.effects.append(Effect(category=category, name=name, effect_id=effect_id, detail=detail))


def _channel_to_track(channel: str) -> str:
    c = channel.upper()
    if c.startswith("V"):
        return c if c[1:].isdigit() else "V1"
    if c.startswith("A"):
        return c
    return "V1"


def _track_from_filename(path: str) -> str:
    m = re.search(r"[_-](V\d+)", os.path.basename(path), re.I)
    return m.group(1).upper() if m else ""

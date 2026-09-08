"""Avid bin (.avb) parser — the richest timeline source.

Reads the top-level sequence from an Avid bin, walks each picture track in
record order and, for every clip, resolves its editor-facing name, source tape,
source timecode and any effects applied to it (Resize, 3D Warp, Timewarp, …).

Clip resolution follows the SourceClip mob chain: the source in-point is the
sum of ``start_time`` down the chain (verified against the matching EDL), the
clip name is the first referenced CompositionMob (subclip / master clip) and
the tape is the physical SourceMob.
"""

from __future__ import annotations

import os

from ..effects import classify
from ..models import Clip, Effect, SequenceOption, Timeline
from ..timecode import frames_to_tc
from . import ParseError

try:
    import avb
    from avb.components import SourceClip, Sequence, Filler
except Exception as exc:  # pragma: no cover
    avb = None
    _IMPORT_ERROR = exc


def parse(path: str, key: int | None = None) -> Timeline:
    if avb is None:  # pragma: no cover
        raise ParseError(f"pyavb is not available: {_IMPORT_ERROR}")

    with avb.open(path) as f:
        candidates = _master_compositions(f.content.mobs)
        if not candidates:
            raise ParseError("No editable sequence with picture tracks found in bin.")
        options = [
            SequenceOption(key=i, name=_seq_name(m), detail=_seq_detail(m))
            for i, m in enumerate(candidates)
        ]
        if key is None or not (0 <= key < len(candidates)):
            key = 0
        comp = candidates[key]

        fps, drop = _sequence_rate(comp)
        tl = Timeline(
            name=getattr(comp, "name", None) or os.path.basename(path),
            fps=fps,
            drop=drop,
            source_path=path,
            source_format="Avid Bin",
            available_sequences=options,
            sequence_key=key,
        )

        picture_tracks = [
            t for t in comp.tracks if getattr(t, "media_kind", None) == "picture"
        ]
        picture_tracks.sort(key=lambda t: getattr(t, "index", 0))

        for tr in picture_tracks:
            track_name = f"V{getattr(tr, 'index', '?')}"
            seq = tr.component
            if not isinstance(seq, Sequence):
                continue
            _walk_track(seq, track_name, fps, drop, tl)

    if not tl.clips:
        tl.warnings.append("Sequence parsed but no clips were found on picture tracks.")
    tl.sorted_by_record()
    return tl


# --------------------------------------------------------------------------- #
# Timeline walking
# --------------------------------------------------------------------------- #
def _walk_track(seq, track_name: str, fps: float, drop: bool, tl: Timeline) -> None:
    pos = 0
    for comp in seq.components:
        length = int(getattr(comp, "length", 0) or 0)
        cname = type(comp).__name__
        if cname == "TransitionEffect":
            # A transition overlaps the surrounding cut: back up so the
            # following clip starts under it rather than after it.
            pos -= length
            continue
        if isinstance(comp, Filler):
            pos += length
            continue

        effects: list[Effect] = []
        _collect_effects(comp, effects)
        src = _first_source_clip(comp)
        clip = Clip(
            index=0,
            track=track_name,
            rec_start=pos,
            rec_end=pos + length,
            fps=fps,
            drop=drop,
            effects=effects,
        )
        if src is not None:
            _resolve_source(src, clip)
        elif effects:
            # Generator / matte / title segment with no underlying source clip.
            clip.clip_name = f"[{effects[0].name}]"
        else:
            clip.clip_name = "(no source)"
        tl.add(clip)
        pos += length


def _collect_effects(node, effects: list[Effect], guard: int = 0) -> None:
    """Gather every effect node in a component's subtree (this timeline only).

    Blend effects such as 3D Warp and Resize keep the real clip in a *foreground*
    track while the background track is filler, so we must search all nested
    tracks and sequences rather than descend a single branch. Referenced mobs
    are never followed here — only the composed timeline component.
    """
    if node is None or guard > 32:
        return
    cname = type(node).__name__
    if cname in ("TrackEffect", "MotionEffect", "TransitionEffect"):
        _record_effect(node, effects)
    pd = getattr(node, "property_data", {})
    for tr in pd.get("tracks", []) or []:
        _collect_effects(getattr(tr, "component", None), effects, guard + 1)
    if isinstance(node, Sequence):
        for c in node.components:
            _collect_effects(c, effects, guard + 1)


def _record_effect(node, effects: list[Effect]) -> None:
    pd = getattr(node, "property_data", {})
    eid = pd.get("effect_id")
    attrs = pd.get("attributes") or {}
    plugin = attrs.get("_EFFECT_PLUGIN_NAME") if hasattr(attrs, "get") else None
    category, _ = classify(eid, plugin)
    detail = ""
    if type(node).__name__ == "MotionEffect":
        detail = _motion_detail(node)
        if category in ("Effect", "") or not category:
            category = "Timewarp"
    # MotionEffects carry no plugin name; fall back to the readable category
    # rather than the raw Avid effect id (e.g. "EFF_ADV_MOTION_CTL").
    name = plugin or category or eid or type(node).__name__
    effects.append(
        Effect(category=category, name=name, effect_id=eid or "", detail=detail)
    )


def _motion_detail(node) -> str:
    pd = getattr(node, "property_data", {})
    speed = pd.get("speed_ratio") or pd.get("speed")
    if speed:
        try:
            num, den = speed
            if den:
                pct = 100.0 * num / den
                return f"{pct:g}%" + (" (reverse)" if pct < 0 else "")
        except (TypeError, ValueError):
            return str(speed)
    return "Motion effect"


# --------------------------------------------------------------------------- #
# Source-clip resolution (name / tape / source timecode)
# --------------------------------------------------------------------------- #
def _resolve_source(src, clip: Clip) -> None:
    cur = src
    offset = 0
    guard = 0
    while cur is not None and isinstance(cur, SourceClip) and getattr(cur, "mob", None) is not None:
        guard += 1
        if guard > 24:
            break
        m = cur.mob
        offset += int(getattr(cur, "start_time", 0) or 0)
        name = getattr(m, "name", None)
        mob_type = getattr(m, "mob_type", None)
        if not clip.clip_name and name and mob_type == "CompositionMob":
            clip.clip_name = name
        if mob_type in ("SourceMob", "MasterMob") and name:
            clip.tape_name = name  # last one wins -> physical tape
        cur = _next_in_chain(m, cur.track_id)

    length = clip.rec_end - clip.rec_start
    clip.src_start = offset
    clip.src_end = offset + length
    if not clip.clip_name:
        clip.clip_name = clip.tape_name or "(unnamed)"


def _next_in_chain(mob, track_id):
    for tr in mob.tracks:
        if getattr(tr, "media_kind", None) != "picture":
            continue
        if getattr(tr, "index", None) != track_id:
            continue
        return _first_source_clip(tr.component)
    return None


def _first_source_clip(comp):
    if comp is None:
        return None
    if isinstance(comp, SourceClip):
        return comp
    pd = getattr(comp, "property_data", {})
    for tr in pd.get("tracks", []) or []:
        s = getattr(tr, "component", None)
        r = _first_source_clip(s)
        if r is not None:
            return r
    if isinstance(comp, Sequence):
        for s in comp.components:
            r = _first_source_clip(s)
            if r is not None:
                return r
    return None


# --------------------------------------------------------------------------- #
# Sequence selection & rate
# --------------------------------------------------------------------------- #
def _master_compositions(mobs):
    """Ordered list of master sequences (CompositionMobs with picture Sequence
    tracks), best first. Subclips / master clips carry a ``usage`` and are
    excluded; if that leaves nothing, fall back to any picture-sequence comp.
    The ordering is deterministic so an option key stays stable between the
    enumeration shown to the user and the re-parse of their choice."""
    masters, fallback = [], []
    for m in mobs:
        if getattr(m, "mob_type", None) != "CompositionMob":
            continue
        pic = [
            t for t in m.tracks
            if getattr(t, "media_kind", None) == "picture"
            and isinstance(t.component, Sequence)
        ]
        if not pic:
            continue
        length = max((int(getattr(t.component, "length", 0) or 0) for t in pic), default=0)
        entry = ((-len(pic), -length, _seq_name(m)), m)
        fallback.append(entry)
        if not getattr(m, "usage", None):
            masters.append(entry)
    chosen = masters or fallback
    chosen.sort(key=lambda x: x[0])
    return [m for _, m in chosen]


def _seq_name(m) -> str:
    return getattr(m, "name", None) or "(unnamed sequence)"


def _seq_detail(m) -> str:
    pic = [t for t in m.tracks
           if getattr(t, "media_kind", None) == "picture" and isinstance(t.component, Sequence)]
    length = max((int(getattr(t.component, "length", 0) or 0) for t in pic), default=0)
    fps, _ = _sequence_rate(m)
    return f"{len(pic)} video track{'s' if len(pic) != 1 else ''} · {frames_to_tc(length, fps)}"


def _sequence_rate(comp) -> tuple[float, bool]:
    for tr in comp.tracks:
        c = tr.component
        rate = getattr(c, "edit_rate", None)
        if rate:
            return float(rate), False
    return 25.0, False


def sequences(path: str) -> list[SequenceOption]:
    """Enumerate selectable sequences in a bin (for the sequence picker)."""
    if avb is None:  # pragma: no cover
        return []
    with avb.open(path) as f:
        cands = _master_compositions(f.content.mobs)
        return [
            SequenceOption(key=i, name=_seq_name(m), detail=_seq_detail(m))
            for i, m in enumerate(cands)
        ]

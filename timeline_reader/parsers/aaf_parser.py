"""AAF parser (pyaaf2).

Walks the top-level composition's timeline slots. Media-only AAF exports (as
produced by an "AAF Picture" flatten) contain source references but no
effects; effect-rich AAFs additionally surface OperationGroups, which are
classified the same way as bin effects.
"""

from __future__ import annotations

import os

from ..effects import classify
from ..models import Clip, Effect, SequenceOption, Timeline
from ..timecode import frames_to_tc
from . import ParseError

try:
    import aaf2
except Exception as exc:  # pragma: no cover
    aaf2 = None
    _IMPORT_ERROR = exc


def parse(path: str, key: int | None = None) -> Timeline:
    if aaf2 is None:  # pragma: no cover
        raise ParseError(f"pyaaf2 is not available: {_IMPORT_ERROR}")

    with aaf2.open(path, "r") as f:
        candidates = _master_compositions(f)
        if not candidates:
            raise ParseError("No composition with a timeline was found in the AAF.")
        options = [
            SequenceOption(key=i, name=c.name or "(unnamed)", detail=_seq_detail(c))
            for i, c in enumerate(candidates)
        ]
        if key is None or not (0 <= key < len(candidates)):
            key = 0
        comp = candidates[key]
        fps, drop = _edit_rate(comp)
        tl = Timeline(
            name=comp.name or os.path.basename(path),
            fps=fps,
            drop=drop,
            source_path=path,
            source_format="AAF",
            available_sequences=options,
            sequence_key=key,
        )
        track_no = 0
        for slot in comp.slots:
            seg = slot.segment
            if type(seg).__name__ != "Sequence":
                continue
            if _slot_media_kind(slot) != "Picture":
                continue
            track_no += 1
            _walk_sequence(seg, f"V{track_no}", fps, drop, tl)

    if not tl.clips:
        tl.warnings.append(
            "This AAF has no timeline clips on picture tracks — it may be a "
            "media-only (flattened) export. Try the Avid bin for full data."
        )
    tl.sorted_by_record()
    return tl


def _walk_sequence(seq, track: str, fps: float, drop: bool, tl: Timeline) -> None:
    pos = 0
    for comp in seq.components:
        length = int(getattr(comp, "length", 0) or 0)
        cname = type(comp).__name__
        if cname == "Transition":
            pos -= length
            continue
        if cname == "Filler":
            pos += length
            continue

        effects: list[Effect] = []
        src = _unwrap(comp, effects)
        clip = Clip(
            index=0,
            track=track,
            rec_start=pos,
            rec_end=pos + length,
            fps=fps,
            drop=drop,
            effects=effects,
        )
        if src is not None:
            _resolve_source(src, clip)
        tl.add(clip)
        pos += length


def _unwrap(comp, effects: list[Effect]):
    node = comp
    guard = 0
    while node is not None and guard < 32:
        guard += 1
        cname = type(node).__name__
        if cname == "SourceClip":
            return node
        if cname == "OperationGroup":
            _record_effect(node, effects)
            segs = list(getattr(node, "segments", []) or [])
            node = segs[0] if segs else None
            continue
        if cname == "Sequence":
            node = _first_segment(node)
            continue
        if cname == "NestedScope":
            slots = list(getattr(node, "slots", []) or [])
            node = slots[0] if slots else None
            continue
        break
    return None


def _record_effect(op, effects: list[Effect]) -> None:
    try:
        opdef = op.operation
        name = opdef.name
        eid = str(getattr(opdef, "auid", "") or "")
    except Exception:  # noqa: BLE001
        name, eid = "Effect", ""
    category, _ = classify(eid, name)
    effects.append(Effect(category=category, name=name or "Effect", effect_id=eid))


def _first_segment(seq):
    for c in seq.components:
        if type(c).__name__ in ("Filler", "Transition"):
            continue
        return c
    return None


def _resolve_source(src, clip: Clip) -> None:
    try:
        mob = src.mob
    except Exception:  # noqa: BLE001
        mob = None
    if mob is not None and getattr(mob, "name", None):
        clip.clip_name = mob.name
    try:
        clip.src_start = int(src["StartTime"].value)
    except Exception:  # noqa: BLE001
        clip.src_start = 0
    clip.src_end = clip.src_start + (clip.rec_end - clip.rec_start)
    # Tape / source name via the physical source mob, best-effort.
    tape = _find_tape(mob)
    if tape:
        clip.tape_name = tape
    if not clip.clip_name:
        clip.clip_name = clip.tape_name or "(unnamed)"


def _find_tape(mob):
    seen = set()
    cur = mob
    guard = 0
    while cur is not None and guard < 24:
        guard += 1
        if id(cur) in seen:
            break
        seen.add(id(cur))
        usage = getattr(cur, "usage", None)
        name = getattr(cur, "name", None)
        if cur.__class__.__name__ == "SourceMob" and name:
            return name
        nxt = None
        for slot in getattr(cur, "slots", []):
            seg = slot.segment
            if type(seg).__name__ == "SourceClip":
                try:
                    nxt = seg.mob
                except Exception:  # noqa: BLE001
                    nxt = None
                break
        cur = nxt
    return None


def _master_compositions(f):
    """Ordered list of picture-bearing compositions, longest first."""
    scored = []
    for m in f.content.mobs:
        if m.__class__.__name__ != "CompositionMob":
            continue
        total, ntracks = _picture_extent(m)
        if ntracks:
            scored.append(((-total, m.name or ""), m))
    scored.sort(key=lambda x: x[0])
    return [m for _, m in scored]


def _picture_extent(m):
    total = 0
    ntracks = 0
    for slot in m.slots:
        seg = slot.segment
        if type(seg).__name__ == "Sequence" and _slot_media_kind(slot) == "Picture":
            ntracks += 1
            total = max(total, int(getattr(seg, "length", 0) or 0))
    return total, ntracks


def _seq_detail(m) -> str:
    total, ntracks = _picture_extent(m)
    fps, _ = _edit_rate(m)
    return f"{ntracks} video track{'s' if ntracks != 1 else ''} · {frames_to_tc(total, fps)}"


def sequences(path: str) -> list[SequenceOption]:
    if aaf2 is None:  # pragma: no cover
        return []
    with aaf2.open(path, "r") as f:
        return [
            SequenceOption(key=i, name=c.name or "(unnamed)", detail=_seq_detail(c))
            for i, c in enumerate(_master_compositions(f))
        ]


def _slot_media_kind(slot) -> str:
    try:
        return slot.media_kind
    except Exception:  # noqa: BLE001
        seg = slot.segment
        try:
            return seg.media_kind
        except Exception:  # noqa: BLE001
            return ""


def _edit_rate(comp) -> tuple[float, bool]:
    for slot in comp.slots:
        rate = getattr(slot, "edit_rate", None)
        if rate:
            try:
                return float(rate), False
            except (TypeError, ValueError):
                pass
    return 25.0, False

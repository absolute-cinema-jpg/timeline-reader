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
from ..keyframes import describe_motion, summarize_keyframes
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

        tl.start_tc = _read_start_tc(comp, fps)

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
            _collect_track_markers(seq, track_name, tl)

        sound_tracks = [
            t for t in comp.tracks if getattr(t, "media_kind", None) == "sound"
        ]
        sound_tracks.sort(key=lambda t: getattr(t, "index", 0))
        for tr in sound_tracks:
            track_name = f"A{getattr(tr, 'index', '?')}"
            seq = _inner_sequence(tr.component)
            if seq is not None:
                _walk_audio_track(seq, track_name, fps, drop, tl, _track_muted(tr))

    if not tl.clips:
        tl.warnings.append("Sequence parsed but no clips were found on picture tracks.")
    tl.sorted_by_record()
    tl.markers.sort(key=lambda m: (m.position, m.track))
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
            # A transition overlaps the surrounding cut: it spans [pos - length,
            # pos] and the following clip is pulled back to start under it. It is
            # an optical in its own right (dissolve, morph cut), so emit it as its
            # own row — no clip name / tape / source, just its record range.
            trans: list[Effect] = []
            _collect_effects(comp, trans, 0, fps, drop)
            if trans:
                tl.add(Clip(
                    index=0, track=track_name, rec_start=pos - length, rec_end=pos,
                    fps=fps, drop=drop, effects=trans, is_transition=True,
                ))
            pos -= length
            continue
        if isinstance(comp, Filler):
            pos += length
            continue

        src = _first_source_clip(comp)
        clip = Clip(
            index=0,
            track=track_name,
            rec_start=pos,
            rec_end=pos + length,
            fps=fps,
            drop=drop,
        )
        _collect_markers(comp, clip)  # sequence-level locators within this segment
        _collect_note(comp, clip)     # timeline clip note (segment comment)
        if src is not None:
            _resolve_source(src, clip)  # sets src_start, needed for keyframe timecodes

        # Effects are collected after the source is resolved so each keyframe's
        # time can be reported as the clip's *source* timecode.
        effects: list[Effect] = []
        _collect_effects(comp, effects, clip.src_start, fps, drop)
        clip.effects = effects

        if src is None:
            # Generator / matte / title segment with no underlying source clip.
            clip.clip_name = f"[{effects[0].name}]" if effects else "(no source)"
        tl.add(clip)
        pos += length


# --------------------------------------------------------------------------- #
# Audio (sound) track walking — for the Music Tracker
# --------------------------------------------------------------------------- #
def _inner_sequence(comp):
    """The picture/sound Sequence inside a track component.

    Sound tracks are often wrapped in a track-level effect (a TrackEffect for
    submaster gain/EQ) whose nested track holds the real Sequence, so descend
    until a Sequence is found rather than assuming the component is one."""
    if comp is None:
        return None
    if isinstance(comp, Sequence):
        return comp
    pd = getattr(comp, "property_data", {})
    for tr in pd.get("tracks", []) or []:
        seq = _inner_sequence(getattr(tr, "component", None))
        if seq is not None:
            return seq
    return None


def _track_muted(tr) -> bool:
    """Whether a sound track is muted in the audio mixer.

    Media Composer records mute per *track* (the mixer's Mute button), not per
    clip — there is no clip-level mute in the model — in the track's
    ``AudioMixerCompMute`` attribute. A clip counts as muted when its track is."""
    attrs = getattr(tr, "attributes", None)
    if attrs is None or not hasattr(attrs, "get"):
        return False
    try:
        return int(attrs.get("AudioMixerCompMute") or 0) != 0
    except (TypeError, ValueError):
        return False


def _walk_audio_track(
    seq, track_name: str, fps: float, drop: bool, tl: Timeline, muted: bool = False
) -> None:
    """Walk one sound track in record order, appending a :class:`Clip` per audio
    segment to ``tl.audio_clips`` (kept apart from picture ``clips`` so the other
    tabs are unaffected).

    Cross dissolves are ``TransitionEffect`` components that overlap the cut, so a
    following segment is pulled back under them exactly as in :func:`_walk_track`.
    Each segment records the length of the dissolve on its head (the transition
    just before it) and tail (the transition just after it) so the Music Tracker
    can optionally include those fades in a cue's in/out. Audio clips sit inside a
    ``PanVolumeEffect`` wrapper; ``_first_source_clip`` descends into it.
    """
    pos = 0
    pending_head = 0
    last: Clip | None = None
    for comp in seq.components:
        length = int(getattr(comp, "length", 0) or 0)
        if type(comp).__name__ == "TransitionEffect":
            if last is not None:
                last.tail_transition = length
            pending_head = length
            pos -= length
            continue
        if isinstance(comp, Filler):
            pos += length
            pending_head = 0
            last = None
            continue

        src = _first_source_clip(comp)
        if src is None:
            pos += length
            pending_head = 0
            last = None
            continue

        clip = Clip(
            index=0,
            track=track_name,
            rec_start=pos,
            rec_end=pos + length,
            fps=fps,
            drop=drop,
            head_transition=pending_head,
            muted=muted,
        )
        _resolve_source(src, clip, media_kind="sound")
        tl.audio_clips.append(clip)
        last = clip
        pending_head = 0
        pos += length


def _read_start_tc(comp, fps: float) -> int:
    """The sequence's record start timecode, in frames.

    A CompositionMob carries one or more timecode tracks; the record TC is the
    one whose rate matches the sequence rate. Media Composer sequences that begin
    on a reel boundary start at e.g. 01:00:00:00, so this offset is what makes the
    hour field meaningful (reel 1, reel 2, …)."""
    nominal = int(round(fps))
    fallback = 0
    for tr in comp.tracks:
        c = tr.component
        if getattr(c, "media_kind", None) != "timecode":
            continue
        if type(c).__name__ != "Timecode":
            continue
        start = int(getattr(c, "start", 0) or 0)
        tc_fps = int(getattr(c, "fps", 0) or 0)
        if tc_fps == nominal:
            return start
        fallback = fallback or start
    return fallback


def _collect_effects(
    node, effects: list[Effect], src_start: int, fps: float, drop: bool, guard: int = 0
) -> None:
    """Gather every effect node in a component's subtree (this timeline only).

    Blend effects such as 3D Warp and Resize keep the real clip in a *foreground*
    track while the background track is filler, so we must search all nested
    tracks and sequences rather than descend a single branch. Referenced mobs
    are never followed here — only the composed timeline component.

    ``src_start`` (the clip's source-in) with ``fps``/``drop`` let each effect's
    keyframes be reported as source timecodes in the Notes column.
    """
    if node is None or guard > 32:
        return
    cname = type(node).__name__
    if cname in ("TrackEffect", "MotionEffect", "TransitionEffect"):
        _record_effect(node, effects, src_start, fps, drop)
    pd = getattr(node, "property_data", {})
    for tr in pd.get("tracks", []) or []:
        _collect_effects(getattr(tr, "component", None), effects, src_start, fps, drop, guard + 1)
    if isinstance(node, Sequence):
        for c in node.components:
            _collect_effects(c, effects, src_start, fps, drop, guard + 1)


def _record_effect(node, effects: list[Effect], src_start: int, fps: float, drop: bool) -> None:
    pd = getattr(node, "property_data", {})
    eid = pd.get("effect_id")
    attrs = pd.get("attributes") or {}
    plugin = attrs.get("_EFFECT_PLUGIN_NAME") if hasattr(attrs, "get") else None
    category, _ = classify(eid, plugin)
    node_type = type(node).__name__
    detail = ""
    if node_type == "MotionEffect":
        # A motion effect resolves to Timewarp / Freeze Frame / Trim to Fill and a
        # speed from its offset & speed maps (the raw effect id is unreliable here).
        category, detail = describe_motion(node, src_start, fps, drop)
    elif node_type == "TransitionEffect":
        detail = ""  # a dissolve / morph cut is named by its category; no keyframes
    else:
        detail = summarize_keyframes(node, src_start, fps, drop)
    # MotionEffects carry no plugin name; fall back to the readable category
    # rather than the raw Avid effect id (e.g. "EFF_ADV_MOTION_CTL").
    name = plugin or category or eid or node_type
    effects.append(
        Effect(category=category, name=name, effect_id=eid or "", detail=detail)
    )


# --------------------------------------------------------------------------- #
# Source-clip resolution (name / tape / source timecode)
# --------------------------------------------------------------------------- #
def _resolve_source(src, clip: Clip, media_kind: str = "picture") -> None:
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
            clip.tape_name = name  # last one wins -> physical tape / file
        _collect_metadata(m, clip)
        for tr in getattr(m, "tracks", []):
            _collect_markers(getattr(tr, "component", None), clip)  # master-clip locators
        cur = _next_in_chain(m, cur.track_id, media_kind)

    # Source duration comes from the source clip itself, not the record length:
    # a motion effect (timewarp / fit-to-fill) consumes a different number of
    # source frames than it occupies on the timeline, so the top SourceClip's
    # length is the real source span. For a plain cut the two are equal.
    src_len = int(getattr(src, "length", 0) or 0) or (clip.rec_end - clip.rec_start)
    clip.src_start = offset
    clip.src_end = offset + src_len
    if not clip.clip_name:
        clip.clip_name = clip.tape_name or "(unnamed)"


# Non-user attributes worth surfacing as columns, mapped to friendly labels.
_DERIVED_ATTRS = {
    "_PJ": "Project",
    "SEQUERNCE_FORMAT_STRING": "Format",  # Avid's own (mis)spelling of the key
    "SEQUENCE_FORMAT_STRING": "Format",
}


def _collect_metadata(mob, clip: Clip) -> None:
    """Merge a mob's bin-column metadata into ``clip.meta``.

    The user-visible bin columns (Scene, Take, Circled, Comment, …) live in the
    ``_USER`` attributes dict; a clip's values are spread across its subclip and
    master mob, so we merge down the chain. The nearest non-empty value wins, so
    a subclip's own value is not overwritten by the master's.
    """
    attrs = getattr(mob, "attributes", None) or {}
    user = attrs.get("_USER") or {}
    for key in getattr(user, "keys", lambda: [])():
        val = _clean(user.get(key))
        if val and not clip.meta.get(key):
            clip.meta[key] = val
    for raw_key, label in _DERIVED_ATTRS.items():
        if raw_key in attrs:
            val = _clean(attrs.get(raw_key))
            if val and not clip.meta.get(label):
                clip.meta[label] = val
    org = attrs.get("_ORG_BIN")
    if org is not None and not clip.meta.get("Origin Bin"):
        name = _clean(getattr(org, "name", None))
        if name:
            clip.meta["Origin Bin"] = name
    if not clip.meta.get("Clip Colour"):
        colour = _clip_colour(attrs)
        if colour:
            clip.meta["Clip Colour"] = colour


def _clean(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    # Avid uses a single space to mean "empty" in some columns (e.g. Circled).
    return "" if text in ("", " ") else text


# Nearest-name palette for Avid clip colours (values in 8-bit RGB).
_COLOUR_NAMES = [
    ("Red", (220, 40, 40)), ("Orange", (240, 130, 40)), ("Yellow", (235, 220, 70)),
    ("Green", (90, 190, 85)), ("Cyan", (70, 200, 210)), ("Blue", (60, 120, 210)),
    ("Purple", (150, 90, 200)), ("Magenta", (210, 70, 180)), ("Pink", (235, 150, 190)),
    ("Brown", (150, 90, 50)), ("White", (240, 240, 240)), ("Black", (20, 20, 20)),
    ("Grey", (128, 128, 128)),
]


def _clip_colour(attrs) -> str:
    """Map a mob's 16-bit ``_COLOR_R/G/B`` to a nearest Avid colour name."""
    if attrs.get("_COLOR_NONE") or "_COLOR_R" not in attrs:
        return ""
    try:
        r = int(attrs["_COLOR_R"]) >> 8
        g = int(attrs["_COLOR_G"]) >> 8
        b = int(attrs["_COLOR_B"]) >> 8
    except (TypeError, ValueError, KeyError):
        return ""
    name, dist = min(
        ((n, (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2) for n, (cr, cg, cb) in _COLOUR_NAMES),
        key=lambda x: x[1],
    )
    # If nothing is close, fall back to a hex value so the info isn't lost.
    return name if dist <= 6000 else f"#{r:02X}{g:02X}{b:02X}"


def _marker_comment(marker) -> str:
    """Best-effort comment text for an Avid locator/marker.

    NOTE: the sample bin has no markers, so this path is unverified against real
    marker data. It reads the marker's referenced Attributes object, preferring
    the standard comment key and otherwise joining any text values.
    """
    attrs = getattr(marker, "attributes", None)
    if attrs is None or not hasattr(attrs, "get"):
        return ""
    for key in ("_ATN_CRM_COM", "CommentMarkUser", "Comment", "comment"):
        val = _clean(attrs.get(key))
        if val:
            return val
    vals = [_clean(v) for v in attrs.values() if isinstance(v, str)]
    return " ".join(v for v in vals if v)


def _collect_markers(node, clip: Clip, seen: set | None = None, depth: int = 0) -> None:
    """Scan a component subtree for markers, appending comments to ``clip.meta``.

    Markers attach as entries in a component's ``attributes`` (single or list).
    """
    from avb.misc import Marker
    if node is None or depth > 12:
        return
    seen = seen if seen is not None else set()
    if id(node) in seen:
        return
    seen.add(id(node))

    attrs = getattr(node, "attributes", None)
    if attrs is not None and hasattr(attrs, "keys"):
        # get(key) resolves object refs that .values() would leave unresolved.
        for key in list(attrs.keys()):
            value = attrs.get(key)
            for item in (value if isinstance(value, list) else [value]):
                if isinstance(item, Marker):
                    comment = _marker_comment(item)
                    if comment:
                        existing = clip.meta.get("Markers", "")
                        clip.meta["Markers"] = f"{existing}; {comment}" if existing else comment

    pd = getattr(node, "property_data", {})
    for tr in pd.get("tracks", []) or []:
        _collect_markers(getattr(tr, "component", None), clip, seen, depth + 1)
    if isinstance(node, Sequence):
        for sub in node.components:
            _collect_markers(sub, clip, seen, depth + 1)


def _collect_note(node, clip: Clip, seen: set | None = None, depth: int = 0) -> None:
    """Gather timeline clip notes from a segment's subtree into ``clip.note``.

    A note the editor typed on a timeline segment (Clip Name > Comments, or the
    Comments row) is stored as the component's ``_COMMENT`` attribute. It can sit
    on the top segment or on a nested effect wrapper (a Resize / FrameFlex holds
    the real clip in a foreground track), so scan the composed subtree — but not
    referenced mobs, so a master clip's own bin Comment never leaks in here.
    Multiple notes on one clip are joined, matching how markers are merged.
    """
    if node is None or depth > 12:
        return
    seen = seen if seen is not None else set()
    if id(node) in seen:
        return
    seen.add(id(node))

    attrs = getattr(node, "attributes", None)
    if attrs is not None and hasattr(attrs, "get"):
        note = _clean(attrs.get("_COMMENT"))
        if note and note not in clip.note.split("; "):
            clip.note = f"{clip.note}; {note}" if clip.note else note

    pd = getattr(node, "property_data", {})
    for tr in pd.get("tracks", []) or []:
        _collect_note(getattr(tr, "component", None), clip, seen, depth + 1)
    if isinstance(node, Sequence):
        for sub in node.components:
            _collect_note(sub, clip, seen, depth + 1)


def _collect_track_markers(seq, track_name: str, tl: Timeline) -> None:
    """Walk one picture track in record order, collecting full timeline markers.

    Positions accumulate exactly as in :func:`_walk_track` so a marker's record
    position matches the clip it sits on. A marker's ``comp_offset`` is its frame
    offset within the component it is attached to, so absolute position is the
    component's record start plus that offset.
    """
    from avb.misc import Marker

    seen: set[int] = set()
    # Locators attached to the track's top-level sequence carry an absolute offset.
    _gather_markers(seq, track_name, 0, tl, seen, Marker, top=True)

    pos = 0
    for comp in seq.components:
        length = int(getattr(comp, "length", 0) or 0)
        if type(comp).__name__ == "TransitionEffect":
            pos -= length
            continue
        _gather_markers(comp, track_name, pos, tl, seen, Marker)
        pos += length


def _gather_markers(
    node, track_name: str, base: int, tl: Timeline, seen: set, marker_cls,
    depth: int = 0, top: bool = False,
) -> None:
    """Find :class:`Marker` objects in ``node``'s attributes (and nested tracks),
    appending a :class:`models.Marker` per unique locator at ``base + comp_offset``."""
    if node is None or depth > 12:
        return
    attrs = getattr(node, "attributes", None)
    if attrs is not None and hasattr(attrs, "keys"):
        # ``attrs.values()`` yields *unresolved* object refs; ``get(key)``
        # dereferences to the real value (e.g. a TimeCrumbList of markers).
        for key in list(attrs.keys()):
            value = attrs.get(key)
            for item in (value if isinstance(value, list) else [value]):
                if isinstance(item, marker_cls) and id(item) not in seen:
                    seen.add(id(item))
                    tl.markers.append(_make_marker(item, track_name, base))

    if top:
        return  # top pass only scans the sequence's own attributes
    pd = getattr(node, "property_data", {})
    for tr in pd.get("tracks", []) or []:
        _gather_markers(
            getattr(tr, "component", None), track_name, base, tl, seen, marker_cls, depth + 1
        )
    if isinstance(node, Sequence):
        for sub in node.components:
            _gather_markers(sub, track_name, base, tl, seen, marker_cls, depth + 1)


def _make_marker(marker, track_name: str, base: int):
    from ..models import Marker as ModelMarker

    offset = int(getattr(marker, "comp_offset", 0) or 0)
    attrs = getattr(marker, "attributes", None)
    return ModelMarker(
        position=base + offset,
        track=track_name,
        comment=_marker_comment(marker),
        colour=_marker_colour(marker),
        user=_marker_attr(attrs, ("_ATN_CRM_USER", "_ATN_CRM_LONG_CRM_USER", "User", "user")),
        date=_marker_attr(attrs, ("_ATN_CRM_DATE", "_ATN_CRM_LONG_CRM_DATE", "Date", "date")),
        length=_marker_int(attrs, ("_ATN_CRM_LENGTH", "_ATN_CRM_MARKER_LENGTH", "length")),
    )


def _marker_attr(attrs, keys) -> str:
    if attrs is None or not hasattr(attrs, "get"):
        return ""
    for key in keys:
        val = _clean(attrs.get(key))
        if val:
            return val
    return ""


def _marker_int(attrs, keys) -> int:
    raw = _marker_attr(attrs, keys)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _marker_colour(marker) -> str:
    """Colour name for a marker.

    Avid records the locator's palette colour by name (e.g. "Red") in the
    ``_ATN_CRM_COLOR`` attribute — authoritative, so prefer it. Only if no name
    is present do we approximate from the 16-bit RGB triple.
    """
    name = _marker_attr(
        getattr(marker, "attributes", None),
        ("_ATN_CRM_COLOR", "_ATN_CRM_COLOR_EXTENDED", "Color", "colour"),
    )
    if name:
        return name
    rgb = getattr(marker, "color", None)
    if isinstance(rgb, (list, tuple)) and len(rgb) >= 3:
        try:
            r, g, b = (int(rgb[i]) >> 8 for i in range(3))
        except (TypeError, ValueError):
            return ""
        name, dist = min(
            ((n, (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2)
             for n, (cr, cg, cb) in _COLOUR_NAMES),
            key=lambda x: x[1],
        )
        return name if dist <= 6000 else f"#{r:02X}{g:02X}{b:02X}"
    return ""


def _next_in_chain(mob, track_id, media_kind: str = "picture"):
    for tr in mob.tracks:
        if getattr(tr, "media_kind", None) != media_kind:
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

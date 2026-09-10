"""Effect keyframe / parameter extraction for the opticals Notes column.

An Avid effect (a ``TrackEffect`` / ``MotionEffect`` node) carries a
``param_list`` of parameters; each animated parameter owns a ``control_track``
whose control points are the keyframes — a time offset plus a value. This module
turns those into a compact, human-readable summary for a clip's Notes cell.

Times are reported as the clip's **source timecode** — a control-point offset is
a frame position from the effect's head, so ``clip src-in + offset`` is where the
keyframe lands in the source clip. Standard spatial keyframes (Resize, 3D Warp,
Reframe) offset cleanly within ``[0, effect length]``; advanced / elastic
keyframes run negative or past the clip end and are clamped to the clip's source
span so the reported time stays a real source timecode.

Two effect families are handled separately:

* **Spatial effects** (:func:`summarize_keyframes`) — position / scale / crop.
  Paired X/Y parameters are combined (``Scale: (100, 100)@tc, (145, 145)@tc``)
  and a static (un-keyframed) crop is still reported.
* **Motion effects** (:func:`describe_motion`) — timewarp / freeze / fit-to-fill.
  The effect's offset map (output→source-frame curve) is the ground truth: a flat
  map is a freeze frame, the map's slope is the play speed, and a variable speed
  map is reported per keyframe as ``speed%@sourceTC``.

Parameter identity is a UUID; pyavb ships the UUID→name table we use to label
them (``AFX_POS_Y_U`` → "Pos Y", ``DVE_SCALE_X_U`` → "Scale X", …).
"""

from __future__ import annotations

from .timecode import frames_to_tc

try:  # pyavb is optional at import time (kept in step with avb_parser)
    from avb.parameter_uuids import PARAMETER_UUIDS as _PARAM_NAMES
except Exception:  # pragma: no cover
    _PARAM_NAMES = {}

# Per-parameter and per-effect caps keep a Notes cell readable rather than
# dumping a machine-sampled curve of hundreds of points.
_MAX_KEYFRAMES_PER_PARAM = 6
_MAX_PARAMS_PER_EFFECT = 6

# Motion-effect parameter names (pyavb's friendly UUID labels).
_SPEED_MAP = "PARAM_SPEED_MAP_U"                 # instantaneous speed ratio curve
_SPEED_OFFSET_MAP = "PARAM_SPEED_OFFSET_MAP_U"   # output→source offset, advanced motion
_OFFSET_MAP = "PARAM_OFFSET_MAP_U"               # output→source offset, fit/trim-to-fill

_CROP_SHORT = {"Crop Left": "L", "Crop Right": "R", "Crop Top": "T", "Crop Bottom": "B"}


# --------------------------------------------------------------------------- #
# Motion effects: timewarp / freeze frame / fit-to-fill
# --------------------------------------------------------------------------- #
def describe_motion(node, src_start: int, fps: float, drop: bool) -> tuple[str, str]:
    """Return ``(category, detail)`` for a ``MotionEffect``.

    ``category`` may be "Freeze Frame", "Trim to Fill" or "Timewarp"; ``detail``
    is a speed percentage (or, for a variable-speed ramp, ``speed%@sourceTC`` per
    keyframe). The offset map is authoritative: Avid stores a bogus ``speed_ratio``
    of ``[length, 1]`` for freezes, so we never trust that field over the map.
    """
    pd = getattr(node, "property_data", {}) or {}
    length = int(pd.get("length", 0) or 0)
    offmap = _points(pd, _SPEED_OFFSET_MAP) or _points(pd, _OFFSET_MAP)
    speedmap = _points(pd, _SPEED_MAP)
    has_raw_offset = _points(pd, _OFFSET_MAP) is not None

    source_span = (offmap[-1][1] - offmap[0][1]) if offmap else None

    # Freeze frame: the source never advances across the effect.
    if source_span is not None and abs(source_span) < 0.5:
        return "Freeze Frame", ""

    slope = source_span / length if (source_span is not None and length) else None

    # Variable-speed ramp: report the speed at each speed keyframe, timed by where
    # that output frame lands in the source via the offset map.
    if speedmap and len({round(v, 4) for _, v in speedmap}) > 1:
        shown = _thin(speedmap)
        parts = []
        for out_off, ratio in shown:
            src_off = _interp(offmap, out_off) if offmap else out_off
            # A fractional source offset sits *within* that integer source frame,
            # so truncate to the frame the playhead is on (don't round up).
            tc = frames_to_tc(src_start + max(0, int(src_off)), fps, drop)
            parts.append(f"{_speed(ratio)}@{tc}")
        detail = ", ".join(parts)
        if len(shown) < len(speedmap):
            detail += f" ({len(speedmap)} kfs)"
        return "Timewarp", detail

    # Fit / Trim to Fill: a raw offset map and no speed map.
    if has_raw_offset and not speedmap:
        return "Trim to Fill", _speed(slope) if slope is not None else _ratio(pd)

    # Constant speed.
    if slope is not None:
        return "Timewarp", _speed(slope)
    if speedmap:  # single-value speed map
        return "Timewarp", _speed(speedmap[0][1])
    return "Timewarp", _ratio(pd)


def _speed(ratio: float) -> str:
    """A speed ratio (1.0 = 100%) as a percent string to ≤2 dp, e.g. ``"34.75%"``."""
    text = f"{ratio * 100:.2f}".rstrip("0").rstrip(".")
    return f"{'0' if text in ('-0', '-0.') else text}%"


def _ratio(pd: dict) -> str:
    """Last-resort speed from the ``speed_ratio`` field when no offset map exists."""
    sr = pd.get("speed_ratio")
    if isinstance(sr, (list, tuple)) and len(sr) == 2 and sr[1]:
        return f"{round(sr[0] / sr[1] * 100)}%"
    return ""


def _interp(samples: list[tuple[float, object]], x: float) -> float:
    """Linear interpolation of a sampled curve at output position ``x``."""
    if not samples:
        return x
    if x <= samples[0][0]:
        return samples[0][1]
    for (x0, y0), (x1, y1) in zip(samples, samples[1:]):
        if x0 <= x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return samples[-1][1]


# --------------------------------------------------------------------------- #
# Spatial effects: position / scale / crop
# --------------------------------------------------------------------------- #
def summarize_keyframes(node, src_start: int, fps: float, drop: bool) -> str:
    """A one-cell summary of a spatial effect's parameters, or ``""``.

    Animated parameters are reported as ``value@sourceTC`` keyframes, with X/Y
    pairs combined. A static (un-keyframed) crop is also reported so a plain crop
    effect is not left blank.
    """
    pd = getattr(node, "property_data", {}) or {}
    param_list = pd.get("param_list")
    if not param_list:
        return ""

    params = _read_params(param_list)                 # [(name, static, points)]
    animated = {name: pts for name, _, pts in params if _is_animated(pts)}
    order = [name for name, _, pts in params if name in animated]

    parts: list[str] = []
    extra = 0
    done: set[str] = set()
    for name in order:
        if name in done:
            continue
        if len(parts) >= _MAX_PARAMS_PER_EFFECT:
            extra += 1
            continue
        base, partner = _pair_partner(name)
        if partner and partner in animated and _same_offsets(animated[name], animated[partner]):
            xk, yk = animated[base + " X"], animated[base + " Y"]
            parts.append(_format_pair(base, xk, yk, src_start, fps, drop))
            done.update((base + " X", base + " Y"))
        else:
            parts.append(_format_single(name, animated[name], src_start, fps, drop))
            done.add(name)

    if extra:
        parts.append(f"+{extra} more")

    crop = _static_crop(params)
    if crop:
        parts.append(crop)
    return "; ".join(parts)


def _read_params(param_list) -> list[tuple[str, object, list]]:
    out = []
    for param in param_list:
        ppd = getattr(param, "property_data", {}) or {}
        track = ppd.get("control_track")
        pts = []
        if track is not None:
            for cp in (getattr(track, "property_data", {}) or {}).get("control_points") or []:
                cpd = getattr(cp, "property_data", {}) or {}
                pts.append((_offset_frames(cpd.get("offset")), cpd.get("value")))
        out.append((_param_name(ppd.get("uuid")), ppd.get("value"), pts))
    return out


def _is_animated(pts: list) -> bool:
    """A parameter is keyframed when it has ≥2 points whose value actually changes."""
    return len(pts) >= 2 and len({repr(v) for _, v in pts}) > 1


def _pair_partner(name: str) -> tuple[str, str | None]:
    """``("Scale", "Scale Y")`` for ``"Scale X"`` (and vice versa), else ``(_, None)``."""
    if name.endswith(" X"):
        return name[:-2], name[:-2] + " Y"
    if name.endswith(" Y"):
        return name[:-2], name[:-2] + " X"
    return name, None


def _same_offsets(a: list, b: list) -> bool:
    return len(a) == len(b) and all(round(oa, 3) == round(ob, 3) for (oa, _), (ob, _) in zip(a, b))


def _format_pair(base, xk, yk, src_start, fps, drop) -> str:
    shown_x, shown_y = _thin(xk), _thin(yk)
    pieces = [
        f"({_fmt_value(xv)}, {_fmt_value(yv)})@{_source_tc(off, src_start, fps, drop)}"
        for (off, xv), (_, yv) in zip(shown_x, shown_y)
    ]
    body = ", ".join(pieces)
    if len(shown_x) < len(xk):
        body += f" ({len(xk)} kfs)"
    return f"{base}: {body}"


def _format_single(name, kfs, src_start, fps, drop) -> str:
    shown = _thin(kfs)
    pieces = [f"{_fmt_value(v)}@{_source_tc(off, src_start, fps, drop)}" for off, v in shown]
    body = ", ".join(pieces)
    if len(shown) < len(kfs):
        body += f" ({len(kfs)} kfs)"
    return f"{name}: {body}"


def _static_crop(params: list[tuple[str, object, list]]) -> str:
    """Report a non-zero, un-keyframed crop (e.g. ``"Crop L 394, R -78"``)."""
    bits = []
    for name, static, pts in params:
        if name in _CROP_SHORT and not _is_animated(pts):
            if isinstance(static, (int, float)) and abs(static) > 0.0001:
                bits.append(f"{_CROP_SHORT[name]} {static:.1f}")  # crop to 1 dp, e.g. 394.0
    return "Crop " + ", ".join(bits) if bits else ""


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def _thin(kfs: list) -> list:
    """Cap a long point list to its first and last, preserving the endpoints."""
    if len(kfs) <= _MAX_KEYFRAMES_PER_PARAM:
        return kfs
    return [kfs[0], kfs[-1]]


def _source_tc(offset: float, src_start: int, fps: float, drop: bool) -> str:
    """Source timecode of the clip at a keyframe (``src-in + offset``).

    The offset is *not* clamped to the clip's edit range: an advanced/elastic
    keyframe can sit earlier in the source than the clip's in-point (a negative
    offset) or past its out-point, and that real source position is what we want.
    Only a negative absolute frame is guarded, so the timecode never wraps.
    """
    return frames_to_tc(max(0, src_start + int(round(offset))), fps, drop)


def _points(pd: dict, param_name: str) -> list[tuple[float, object]] | None:
    """Control points ``[(offset_frames, value), …]`` of a named parameter, or ``None``."""
    for param in pd.get("param_list") or []:
        ppd = getattr(param, "property_data", {}) or {}
        if _param_name(ppd.get("uuid")) != param_name:
            continue
        track = ppd.get("control_track")
        if track is None:
            return None
        pts = []
        for cp in (getattr(track, "property_data", {}) or {}).get("control_points") or []:
            cpd = getattr(cp, "property_data", {}) or {}
            pts.append((_offset_frames(cpd.get("offset")), cpd.get("value")))
        return pts
    return None


def _offset_frames(offset) -> float:
    """A control point's offset (a ``[num, den]`` rational) as a frame count."""
    if isinstance(offset, (list, tuple)) and len(offset) == 2:
        num, den = offset
        try:
            return num / den if den else float(num)
        except (TypeError, ZeroDivisionError):
            return 0.0
    try:
        return float(offset)
    except (TypeError, ValueError):
        return 0.0


def _param_name(uuid) -> str:
    """Raw Avid parameter name for a UUID (``AFX_POS_Y_U`` etc.), pretty for spatial."""
    raw = _PARAM_NAMES.get(str(uuid))
    if not raw:
        return "Param"
    # Motion parameters are matched by their raw names, so leave those intact;
    # spatial parameters (AFX_*/DVE_*) get a human label.
    if raw.startswith("PARAM_"):
        return raw
    name = raw
    for prefix in ("AFX_", "DVE_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    if name.endswith("_U"):
        name = name[:-2]
    return name.replace("_", " ").title()


def _fmt_value(value) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        text = f"{value:.2f}".rstrip("0").rstrip(".")
        return "0" if text in ("-0", "-0.") else text  # kill negative-zero artefacts
    if isinstance(value, (list, tuple)) and len(value) == 2:
        num, den = value  # a rational value
        try:
            return _fmt_value(num / den) if den else str(num)
        except (TypeError, ZeroDivisionError):
            return str(value)
    return str(value)

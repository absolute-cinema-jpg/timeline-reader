"""Read SubCap subtitles straight from an Avid bin (.avb).

Avid Media Composer's *SubCap* effect stores each on-screen subtitle as its own
effect segment on a video track: the segment's record in/out give the caption
timing, and the effect's first user parameter (a ``CFUserParam``) holds the
caption text. ``pyavb`` exposes both, so we can rebuild exactly the cue list the
Avid Caption (.txt) export would produce — directly from the timeline, and with
multi-line captions intact (the flat .txt export keeps only the first line).

This is the same bin the other tabs already read, so the Captions tab loads the
same file as everything else instead of a separate caption export.
"""

from __future__ import annotations

from .captions import CaptionDoc, Cue
from .models import SequenceOption
from .parsers import ParseError
from .parsers.avb_parser import (
    _read_start_tc,
    _sequence_rate,
    candidates,
    open_bin,
    sequence_options,
)

try:
    import avb
    from avb.components import Filler, Sequence
except Exception as exc:  # pragma: no cover - avb is a hard dependency in practice
    avb = None
    _IMPORT_ERROR = exc

# The AVX effect id of Avid's stock "SubCap" subtitle plugin. Every subtitle in a
# SubCap workflow is one segment carrying this effect; matching on it keeps the
# subtitle track apart from other title effects (e.g. Marquee VFX/credit cards).
SUBCAP_EFFECT_IDS = {"E4FE520A-B815-447F-A969-2D5E1C5F6C14"}


def caption_sequences(path: str) -> list[SequenceOption]:
    """Enumerate the bin's selectable sequences (same ordering as the other tabs)."""
    if avb is None:  # pragma: no cover
        return []
    with open_bin(path) as f:
        return sequence_options(f)


def parse_captions(path: str, key: int | None = None) -> CaptionDoc:
    """Build a :class:`CaptionDoc` from the SubCap subtitles on one sequence."""
    with open_bin(path) as f:
        return parse_captions_open(f, path, key)


def parse_captions_open(f, path: str, key: int | None = None) -> CaptionDoc:
    """Caption parse over an already-open bin, so the timeline parse and this
    one can share a single open (see :mod:`timeline_reader.loader`)."""
    cands = candidates(f)
    if not cands:
        raise ParseError("No editable sequence with picture tracks found in bin.")
    if key is None or not (0 <= key < len(cands)):
        key = 0
    comp = cands[key]

    fps, drop = _sequence_rate(comp)
    start = _read_start_tc(comp, fps)
    doc = CaptionDoc(fps=fps, drop=drop, source_path=path)
    doc.start_tc = start
    doc.available_sequences = sequence_options(f)
    doc.sequence_key = key
    doc.sequence_name = getattr(comp, "name", "") or ""

    found: list[tuple[int, int, str, bool]] = []
    for tr in comp.tracks:
        if getattr(tr, "media_kind", None) != "picture":
            continue
        seq = tr.component
        if not isinstance(seq, Sequence):
            continue
        _walk_track(seq, found)

    # Record order; a stable second key keeps identically-timed cues deterministic.
    found.sort(key=lambda c: (c[0], c[1]))
    for i, (rec_in, rec_out, text, muted) in enumerate(found, 1):
        doc.cues.append(
            Cue(
                index=i,
                start=start + rec_in,
                end=start + rec_out,
                lines=text.split("\n"),
                muted=muted,
            )
        )

    if not doc.cues:
        doc.warnings.append(
            "No SubCap subtitles found on this sequence. Pick another sequence, or "
            "check the subtitles were made with Avid's SubCap effect."
        )
    return doc


# --------------------------------------------------------------------------- #
# Timeline walking
# --------------------------------------------------------------------------- #
def _walk_track(seq, found: list[tuple[int, int, str, bool]]) -> None:
    """Append ``(rec_in, rec_out, text, muted)`` for every SubCap segment on a track.

    Record positions accumulate exactly as the main bin parser walks a track, so
    a caption's in/out matches where it sits on the timeline. Transitions overlap
    the cut (pull the following segment back), and fillers are gaps.
    """
    pos = 0
    for comp in seq.components:
        length = int(getattr(comp, "length", 0) or 0)
        if type(comp).__name__ == "TransitionEffect":
            pos -= length
            continue
        if isinstance(comp, Filler):
            pos += length
            continue
        fx = _find_subcap(comp)
        if fx is not None:
            text = _subcap_text(fx)
            if text:
                found.append((pos, pos + length, text, _is_disabled(comp)))
        pos += length


def _is_disabled(node, depth: int = 0) -> bool:
    """Whether a timeline segment is disabled ("muted") in Media Composer.

    Disabling a clip wraps it in a ``Selector`` that plays a filler instead, and
    marks it with the ``_DISABLE_CLIP_FLAG`` attribute. The flag sits on the
    wrapper rather than the SubCap effect itself, so check the enclosing
    components too — the effect is nested inside the selector.
    """
    if node is None or depth > 8:
        return False
    attrs = getattr(node, "attributes", None)
    if attrs is not None and hasattr(attrs, "get"):
        try:
            if int(attrs.get("_DISABLE_CLIP_FLAG") or 0):
                return True
        except (TypeError, ValueError):
            pass
    pd = getattr(node, "property_data", {}) or {}
    for tr in pd.get("tracks", []) or []:
        if _is_disabled(getattr(tr, "component", None), depth + 1):
            return True
    return False


def _find_subcap(node, depth: int = 0):
    """The SubCap ``TrackEffect`` within a component's subtree, if any."""
    if node is None or depth > 24:
        return None
    pd = getattr(node, "property_data", {}) or {}
    if pd.get("effect_id") in SUBCAP_EFFECT_IDS:
        return node
    for tr in pd.get("tracks", []) or []:
        r = _find_subcap(getattr(tr, "component", None), depth + 1)
        if r is not None:
            return r
    if isinstance(node, Sequence):
        for c in node.components:
            r = _find_subcap(c, depth + 1)
            if r is not None:
                return r
    return None


def _subcap_text(fx) -> str:
    """The caption text held in a SubCap effect's first text user-parameter.

    SubCap keeps its per-caption values in ``CFUserParam`` blobs on the effect's
    ``param_list``; the first one that decodes to readable text is the caption
    (later blobs hold the font name and numeric style values). Trailing blanks —
    which Avid pads and the flat .txt export drops — are trimmed per line.
    """
    for p in fx.property_data.get("param_list") or []:
        if type(p).__name__ != "ParameterItem":
            continue
        value = p.property_data.get("value")
        if type(value).__name__ != "CFUserParam":
            continue
        data = bytes(value.property_data.get("data") or b"").rstrip(b"\x00")
        if not data:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if _is_readable(text):
            return _tidy(text)
    return ""


def _is_readable(text: str) -> bool:
    """True for real caption text (printable, plus tabs/newlines) — not a binary
    or serialized-style blob that also happens to live in a CFUserParam."""
    if not text.strip():
        return False
    return all(ch in "\n\t" or ch >= " " for ch in text)


def _tidy(text: str) -> str:
    lines = [ln.strip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    while lines and not lines[0]:
        lines.pop(0)
    return "\n".join(lines)

"""Effect classification.

Maps raw Avid effect identifiers / plugin names to normalised categories and
decides which categories belong on an *opticals* list for the online house.

The rules are data-driven so new effects are one line to add. Matching is done
on the Avid ``effect_id`` first (exact, then prefix), falling back to the
plugin name. Anything unrecognised is classified ``Other`` and, by default,
excluded from the opticals list.
"""

from __future__ import annotations

# effect_id (exact)            -> (category, opticals?)
_EXACT: dict[str, tuple[str, bool]] = {
    "EFF2_BLEND_RESIZE": ("Resize", True),
    "EFF2_SBLEND": ("3D Warp", True),
    "EFF_TIMEWARP.MOTION_CTL": ("Timewarp", True),
    "EFF_ADV_MOTION_CTL": ("Timewarp", True),
    "EFF_MOTION_CTL": ("Timewarp", True),
    "EFF_MOTION": ("Motion Effect", True),
    "EFF_FLIP": ("Flip", True),
    "EFF_FLOP": ("Flop", True),
    "EFF_FLIP_FLOP": ("Flip-Flop", True),
    "EFF2_RGB_COLOR_CORRECTION": ("Colour Correction", False),
    "EFF2_BLEND_DISSOLVE": ("Dissolve", True),
    "EFF_ANIMATTE": ("AniMatte", True),
    "EFF_BLEND_SUBMASTER": ("Submaster", False),
    "INT_EFF_SPATIAL_ADAPTER": ("Auto Reformat", False),
    "INT_EFF_TIMECODE_BURNIN": ("Timecode Burn-in", False),
}

# effect_id prefix -> (category, opticals?)   (checked after exact match)
_PREFIX: tuple[tuple[str, str, bool], ...] = (
    ("EFF2_BLEND_MASK", "Mask", True),
    ("EFF_MASK", "Mask", True),
    ("EFF_PAN", "Reframe", True),
    ("EFF2_BLEND_PIP", "Picture-in-Picture", True),
    ("EFF_TIMEWARP", "Timewarp", True),
    ("EFF_MOTION", "Motion Effect", True),
    ("EFF2_RGB_COLOR", "Colour Correction", False),
    ("EFF2_BLEND_DISSOLVE", "Dissolve", True),
    ("EFF2_BLEND_FADE", "Fade", False),
)

# Fallback matching on the human plugin name (lower-cased substring).
_BY_NAME: tuple[tuple[str, str, bool], ...] = (
    ("resize", "Resize", True),
    ("3dwarp", "3D Warp", True),
    ("3d warp", "3D Warp", True),
    ("timewarp", "Timewarp", True),
    ("motion", "Motion Effect", True),
    ("mask", "Mask", True),
    ("flip", "Flip", True),
    ("flop", "Flop", True),
    ("reformat", "Auto Reformat", False),
    ("color correction", "Colour Correction", False),
    ("colour correction", "Colour Correction", False),
    ("dissolve", "Dissolve", True),
    ("animatte", "AniMatte", True),
    ("submaster", "Submaster", False),
    ("title", "Title", False),
    ("subcap", "Subtitle", False),
    ("fluidmorph", "FluidMorph", True),
)

# Categories derived in the parser (not via the tables above) rather than from a
# raw effect id — motion effects resolve to these from their offset/speed maps.
_DERIVED_OPTICAL = {"Freeze Frame", "Trim to Fill"}

_OPTICAL_CATEGORIES = {
    cat for cat, opt in _EXACT.values() if opt
} | {cat for _, cat, opt in _PREFIX if opt} | {cat for _, cat, opt in _BY_NAME if opt} | _DERIVED_OPTICAL


def classify(effect_id: str | None, plugin_name: str | None) -> tuple[str, bool]:
    """Return ``(category, is_optical)`` for a raw effect id / plugin name."""
    eid = (effect_id or "").strip()
    if eid in _EXACT:
        return _EXACT[eid]
    for prefix, cat, opt in _PREFIX:
        if eid.startswith(prefix):
            return cat, opt
    name = (plugin_name or "").strip().lower()
    for needle, cat, opt in _BY_NAME:
        if needle in name:
            return cat, opt
    # Unknown effect: surface it by its plugin name but keep it off opticals.
    label = (plugin_name or eid or "Effect").strip()
    return label, False


def is_optical_category(category: str) -> bool:
    return category in _OPTICAL_CATEGORIES

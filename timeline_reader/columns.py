"""Configurable report columns.

A report is a fixed set of built-in columns plus any metadata columns discovered
on the loaded timeline (bin columns such as Scene / Take / Comment, or unmapped
tab-delimited headings). Each column is individually toggleable; the built-in
set matches what the app shipped with, so defaults are unchanged.

The user's include/exclude choices are remembered per report via QSettings, keyed
by column id — so enabling "Take" once keeps it on across sessions and across
different files that also expose a "Take" column.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterator

from .models import Clip, Effect, Timeline
from .timecode import frames_to_duration, frames_to_tc

META_PREFIX = "meta:"


@dataclass
class RowCtx:
    """Everything a column getter might need for one output row."""

    tl: Timeline
    clip: Clip
    n: int                       # 1-based row number
    effect: Effect | None = None


@dataclass
class ColumnDef:
    id: str
    label: str
    group: str
    default: bool
    getter: Callable[[RowCtx], str]


# --------------------------------------------------------------------------- #
# Built-in column getters
# --------------------------------------------------------------------------- #
def _tc(frames_attr: str) -> Callable[[RowCtx], str]:
    def get(ctx: RowCtx) -> str:
        return frames_to_tc(getattr(ctx.clip, frames_attr), ctx.tl.fps, ctx.tl.drop)
    return get


_CORE_BEFORE = [
    ColumnDef("index", "#", "Core", True, lambda c: str(c.n)),
    ColumnDef("track", "Track", "Core", True, lambda c: c.clip.track),
]
_CLIP_IDENTITY = [
    ColumnDef("clip_name", "Clip Name", "Core", True, lambda c: c.clip.clip_name),
    ColumnDef("tape_name", "Tape / Source", "Core", True, lambda c: c.clip.tape_name),
]
_EFFECT_COLS = [
    ColumnDef("effect", "Effect", "Effect", True, lambda c: c.effect.category if c.effect else ""),
    ColumnDef("effect_type", "Type", "Effect", True, lambda c: c.effect.name if c.effect else ""),
]
_TIMECODES = [
    ColumnDef("rec_in", "Rec In", "Timecode", True, _tc("rec_start")),
    ColumnDef("rec_out", "Rec Out", "Timecode", True, _tc("rec_end")),
    ColumnDef("src_in", "Src In", "Timecode", True, _tc("src_start")),
    ColumnDef("src_out", "Src Out", "Timecode", True, _tc("src_end")),
    ColumnDef("duration", "Duration", "Timecode", True,
              lambda c: frames_to_duration(c.clip.duration, c.tl.fps)),
    ColumnDef("effect_id", "Effect ID", "Effect", False,
              lambda c: c.effect.effect_id if c.effect else ""),
    ColumnDef("notes", "Notes", "Effect", False, lambda c: c.effect.detail if c.effect else ""),
]


def _opticals_builtin() -> list[ColumnDef]:
    # Order chosen to match the original opticals report layout.
    return [
        _CORE_BEFORE[0], _CORE_BEFORE[1],
        _EFFECT_COLS[0], _EFFECT_COLS[1],
        _CLIP_IDENTITY[0], _CLIP_IDENTITY[1],
        _col("rec_in"), _col("rec_out"), _col("src_in"), _col("src_out"),
        _col("duration"),
        _make("notes", "Notes", "Effect", True, lambda c: c.effect.detail if c.effect else ""),
        _col("effect_id"),
    ]


def _cliplist_builtin() -> list[ColumnDef]:
    return [
        _CORE_BEFORE[0], _CORE_BEFORE[1],
        _CLIP_IDENTITY[0], _CLIP_IDENTITY[1],
        _col("src_in"), _col("src_out"), _col("rec_in"), _col("rec_out"),
        _col("duration"),
    ]


_BY_ID = {c.id: c for c in _TIMECODES}


def _col(cid: str) -> ColumnDef:
    return _BY_ID[cid]


def _make(cid, label, group, default, getter) -> ColumnDef:
    return ColumnDef(cid, label, group, default, getter)


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
@dataclass
class Report:
    key: str
    builtin: list[ColumnDef]
    per_effect: bool                          # opticals iterate effects; clip list iterates clips
    optical_only: bool = False

    def all_columns(self, tl: Timeline) -> list[ColumnDef]:
        """Built-in columns followed by one column per discovered metadata key."""
        cols = list(self.builtin)
        for key in tl.meta_columns:
            cols.append(
                ColumnDef(
                    id=META_PREFIX + key,
                    label=key,
                    group="Metadata",
                    default=False,
                    getter=(lambda c, k=key: c.clip.meta.get(k, "")),
                )
            )
        return cols

    def iter_ctx(self, tl: Timeline) -> Iterator[RowCtx]:
        from .effects import is_optical_category
        n = 0
        for clip in tl.sorted_by_record():
            if self.per_effect:
                for eff in clip.effects:
                    if self.optical_only and not is_optical_category(eff.category):
                        continue
                    n += 1
                    yield RowCtx(tl, clip, n, eff)
            else:
                n += 1
                yield RowCtx(tl, clip, n)

    def columns_for(self, tl: Timeline, selection: "ColumnSelection") -> list[ColumnDef]:
        """The included columns, in effective (custom or canonical) order."""
        cols = [c for c in self.all_columns(tl) if selection.effective(c)]
        return selection.ordered(cols)

    def render(
        self, tl: Timeline, selection: "ColumnSelection"
    ) -> tuple[list[ColumnDef], list[list[str]]]:
        """Ordered column defs plus the data rows — the tab needs the defs so it
        can map a dragged header position back to a column id."""
        cols = self.columns_for(tl, selection)
        rows = [[c.getter(ctx) for c in cols] for ctx in self.iter_ctx(tl)]
        return cols, rows

    def build(self, tl: Timeline, selection: "ColumnSelection") -> tuple[list[str], list[list[str]]]:
        cols, rows = self.render(tl, selection)
        return [c.label for c in cols], rows


OPTICALS_REPORT = Report("opticals", _opticals_builtin(), per_effect=True, optical_only=True)
CLIPLIST_REPORT = Report("cliplist", _cliplist_builtin(), per_effect=False)


# --------------------------------------------------------------------------- #
# Selection (include/exclude) with persistence
# --------------------------------------------------------------------------- #
_ORDER_KEY = "__order__"


@dataclass
class ColumnSelection:
    """Include/exclude state plus a custom column order.

    ``effective(col)`` = per-column user override, else the column's default.
    ``order`` is a saved list of column ids (it may name columns not present in
    a given file, and omit newly-seen ones); :meth:`ordered` sorts a column list
    by it, leaving unlisted columns in their canonical order at the end.
    """

    report_key: str
    overrides: dict[str, bool] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)

    def effective(self, col: ColumnDef) -> bool:
        return self.overrides.get(col.id, col.default)

    def set(self, col_id: str, on: bool) -> None:
        self.overrides[col_id] = on

    def set_order(self, ids: list[str]) -> None:
        self.order = list(ids)

    def ordered(self, cols: list[ColumnDef]) -> list[ColumnDef]:
        pos = {cid: i for i, cid in enumerate(self.order)}
        # The "#" (index) column is always pinned first; a stray drag can't bury
        # it. Otherwise: listed columns by saved position, then the rest in their
        # canonical order (all share the same fallback key, so the sort is stable).
        def key(c: ColumnDef) -> int:
            if c.id == "index":
                return -1
            return pos.get(c.id, len(pos))
        return sorted(cols, key=key)

    def reset(self) -> None:
        self.overrides.clear()
        self.order.clear()

    # -- persistence (QSettings); imported lazily so non-GUI use has no Qt dep --
    def load(self) -> "ColumnSelection":
        try:
            from PySide6.QtCore import QSettings
        except Exception:  # pragma: no cover
            return self
        s = QSettings("TimelineReader", "TimelineReader")
        s.beginGroup(f"columns/{self.report_key}")
        raw_order = s.value(_ORDER_KEY, [])
        if isinstance(raw_order, str):
            raw_order = [raw_order]
        self.order = list(raw_order) if raw_order else []
        for cid in s.childKeys():
            if cid == _ORDER_KEY:
                continue
            self.overrides[cid] = s.value(cid, type=bool)
        s.endGroup()
        return self

    def save(self) -> None:
        try:
            from PySide6.QtCore import QSettings
        except Exception:  # pragma: no cover
            return
        s = QSettings("TimelineReader", "TimelineReader")
        s.beginGroup(f"columns/{self.report_key}")
        s.remove("")  # clear stale keys so removed overrides don't linger
        s.setValue(_ORDER_KEY, self.order)
        for cid, on in self.overrides.items():
            s.setValue(cid, on)
        s.endGroup()

"""Convenience wrappers that build report tables with default columns.

The real column logic lives in :mod:`timeline_reader.columns`. These helpers
render a report with its default column selection — handy for headless use,
tests and scripting. The UI drives :class:`~timeline_reader.columns.Report`
directly so it can honour the user's include/exclude choices.
"""

from __future__ import annotations

from .columns import CLIPLIST_REPORT, OPTICALS_REPORT, ColumnSelection
from .models import Timeline


def opticals_rows(tl: Timeline) -> tuple[list[str], list[list[str]]]:
    return OPTICALS_REPORT.build(tl, ColumnSelection(OPTICALS_REPORT.key))


def cliplist_rows(tl: Timeline) -> tuple[list[str], list[list[str]]]:
    return CLIPLIST_REPORT.build(tl, ColumnSelection(CLIPLIST_REPORT.key))

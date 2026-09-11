"""Tag Finder tab: search a timeline for clips carrying a given clip note.

The editor preps a sequence in Media Composer by typing the same word into the
timeline clip note (the segment Comment) of every clip they want to collect —
say "stock" on every stock-footage shot. Loading the bin here and typing that
word lists exactly those clips, each with its full source/record timecode, tape
and clip name, ready to copy, export or turn into Avid markers.

It reuses :class:`TimelineReportTab` wholesale — drop zone, table, columns,
delete/undo, export — and adds a search box that narrows the rows to the notes
that match. The underlying report only ever yields clips that carry a note, so
an empty search still shows every tagged clip as a browse aid.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from ..columns import TAGFINDER_REPORT
from ..rowset import RowSet
from .report_tab import TimelineReportTab


class TagFinderTab(TimelineReportTab):
    def __init__(self, parent=None):
        self._tagged_total = 0
        super().__init__(
            report=TAGFINDER_REPORT,
            drop_title="Drop a timeline file",
            drop_sub="Avid bin (.avb) carries timeline clip notes",
            export_basename="tagged",
            empty_hint="Load a sequence with timeline clip notes",
            count_label="Matches",
            description=(
                "Finds clips by their <b>timeline clip note</b> (the segment "
                "Comment typed in Media Composer). Tag shots in Avid first — e.g. "
                "put “stock” on every stock shot — then load the bin and "
                "search that word to collect them. <b>Only clips that carry a "
                "note appear</b>; an empty search lists them all. Turn on "
                "<b>Exact text matching</b> to require the note to equal the tag "
                "exactly."
            ),
            parent=parent,
        )

    # ---- search -----------------------------------------------------------
    def _toolbar(self):
        """A dedicated search row above the base toolbar (sequence picker,
        columns, clear/reset). Keeping the tag field, exact-match toggle and the
        base controls on separate lines stops them crowding — and overlapping —
        each other when the window is narrow."""
        self._search = QLineEdit()
        self._search.setPlaceholderText('Type a clip note to find, e.g. "stock"')
        self._search.setClearButtonEnabled(True)
        self._search.setMinimumWidth(220)
        self._search.textChanged.connect(self._on_search_changed)
        self._exact = QCheckBox("Exact text matching")
        self._exact.setToolTip(
            "Off: find notes that contain the tag (so \"stock\" finds "
            "\"stock footage\").\nOn: keep only notes that are exactly the tag."
        )
        self._exact.toggled.connect(self._on_search_changed)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        search_row.addWidget(QLabel("Tag:"))
        search_row.addWidget(self._search, 1)  # the field takes the spare width
        search_row.addWidget(self._exact)

        container = QVBoxLayout()
        container.setSpacing(10)
        container.addLayout(search_row)
        container.addLayout(super()._toolbar())
        return container

    def _compute_contexts(self) -> list:
        """Tagged clips, narrowed to the ones whose note matches the search term
        (case-insensitive). Off = substring match, so "stock" finds "stock
        footage"; on = the whole note must equal the term. Empty search shows
        every tagged clip."""
        tagged = list(self._report.iter_ctx(self._timeline))
        self._tagged_total = len(tagged)
        term = self._search.text().strip().lower()
        if not term:
            contexts = tagged
        elif self._exact.isChecked():
            # A clip can carry several notes joined with "; "; match any one.
            contexts = [
                c for c in tagged
                if term in [p.strip().lower() for p in c.clip.note.split(";")]
            ]
        else:
            contexts = [c for c in tagged if term in c.clip.note.lower()]
        self._update_empty_hint(term)
        return contexts

    def _on_search_changed(self, *_):
        """Re-narrow the table as the tag is typed. A new search set makes any
        earlier row deletions moot, so the RowSet is reset (as the Music Tracker
        does when its options change)."""
        if self._timeline is None:
            return
        self._all_contexts = self._compute_contexts()
        self._rowset = RowSet()
        self._rebuild_rows()
        term = self._search.text().strip()
        if term:
            self.status.emit(
                f'{len(self._all_contexts)} clip'
                f'{"" if len(self._all_contexts) == 1 else "s"} tagged "{term}"'
            )

    def _update_empty_hint(self, term: str) -> None:
        """Message shown when nothing is in the table, tuned to why it's empty."""
        if self._tagged_total == 0:
            self._empty_hint = "This sequence has no timeline clip notes"
        elif term:
            self._empty_hint = (
                f'No clips tagged "{term}"  ·  '
                f"{self._tagged_total} tagged clip"
                f"{'' if self._tagged_total == 1 else 's'} in this sequence"
            )
        else:
            self._empty_hint = "Type a tag to filter the tagged clips"

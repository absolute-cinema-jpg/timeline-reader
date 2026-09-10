"""Row deletion state for the preview tables — delete, undo, reset.

Rows are tracked by a caller-supplied *key* (a stable identity) rather than a
position, so deletions survive rebuilds that re-render the same rows (a column
reorder, say) while naturally lapsing when the underlying data changes (a new
file or sequence). This is UI-agnostic and Qt-free so it can be unit-tested.
"""

from __future__ import annotations

from typing import Hashable, Sequence


class RowSet:
    """Which rows have been deleted, with a single-step-per-action undo stack."""

    def __init__(self) -> None:
        self._deleted: set[Hashable] = set()
        self._undo: list[list[Hashable]] = []  # each entry = one delete action

    # ---- queries ----------------------------------------------------------
    def is_deleted(self, key: Hashable) -> bool:
        return key in self._deleted

    def active_items(self, keys: Sequence[Hashable], items: Sequence) -> list:
        """Items whose key is not deleted, in the given order."""
        return [it for k, it in zip(keys, items) if k not in self._deleted]

    def active_keys(self, keys: Sequence[Hashable]) -> list:
        return [k for k in keys if k not in self._deleted]

    @property
    def has_deletions(self) -> bool:
        return bool(self._deleted)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    # ---- mutations --------------------------------------------------------
    def delete(self, keys) -> int:
        """Delete the given keys (already-deleted ones are ignored). Returns the
        number newly deleted; records them as one undoable action."""
        fresh = [k for k in keys if k not in self._deleted]
        if not fresh:
            return 0
        self._deleted.update(fresh)
        self._undo.append(fresh)
        return len(fresh)

    def delete_display(self, display_rows, active_keys: Sequence[Hashable]) -> int:
        """Delete rows given by their positions in the current *active* order."""
        to_delete = [active_keys[i] for i in display_rows if 0 <= i < len(active_keys)]
        return self.delete(to_delete)

    def undo(self) -> int:
        """Restore the most recent delete action. Returns how many rows returned."""
        if not self._undo:
            return 0
        last = self._undo.pop()
        self._deleted.difference_update(last)
        return len(last)

    def reset(self) -> None:
        """Restore every deleted row."""
        self._deleted.clear()
        self._undo.clear()

"""Load progress: how far a slow parse has got, for the drop zones' loading bar.

A parse runs on a worker thread and, for a big bin, spends its time in three
places — pyavb indexing every object header on open, scanning the bin's mobs
for its sequences, and walking the chosen sequence. Each reports through a
:class:`Phase` that maps its own 0..1 into a slice of the whole load, and the
:class:`Progress` behind them tells the registered listeners whenever the
whole-number percent moves. Listeners are called on the parsing thread.
"""

from __future__ import annotations

import threading
from typing import Callable

Listener = Callable[[str, int], None]  # (path, percent)

_listeners: list[Listener] = []
_lock = threading.Lock()


def add_listener(fn: Listener) -> None:
    with _lock:
        _listeners.append(fn)


def remove_listener(fn: Listener) -> None:
    with _lock:
        if fn in _listeners:
            _listeners.remove(fn)


class Progress:
    """Progress of one load, as a fraction 0..1 of the whole."""

    def __init__(self, path: str):
        self.path = path
        self._percent = -1

    def set(self, fraction: float) -> None:
        percent = max(0, min(100, int(fraction * 100)))
        if percent == self._percent:
            return
        self._percent = percent
        with _lock:
            listeners = list(_listeners)
        for fn in listeners:
            fn(self.path, percent)

    def phase(self, start: float, end: float) -> "Phase":
        return Phase(self, start, end)


class Phase:
    """One stage of a load, reporting ``done`` of ``total`` steps as the
    ``start``..``end`` slice of the whole bar."""

    def __init__(self, progress: Progress | None, start: float, end: float):
        self._progress = progress
        self._start = start
        self._span = end - start

    def step(self, done: int, total: int) -> None:
        if self._progress is not None and total > 0:
            self._progress.set(self._start + self._span * min(done, total) / total)

    def finish(self) -> None:
        if self._progress is not None:
            self._progress.set(self._start + self._span)


def phase(progress: Progress | None, start: float, end: float) -> Phase:
    """A :class:`Phase` that is a no-op when there is nothing to report to."""
    return Phase(progress, start, end)

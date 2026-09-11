"""One walk per file: the cached, de-duplicated loading shared by every tab.

Choosing a timeline file in one tab loads it in all of them, and each tab
used to run its own full parse — four complete walks of the bin racing on
worker threads (and, being pure Python, taking turns on the GIL) plus a fifth
open for the subtitles. This module makes that a single parse: the first
caller does the work while the others wait on the lock and pick up the result,
and an Avid bin is opened once to produce both the :class:`Timeline` and the
:class:`CaptionDoc`.

Results are keyed by the file's path, size and modification time plus the
chosen sequence, so re-dropping an unchanged file (or a sibling tab switching
to a sequence another tab already showed) is instant, while a bin re-saved in
Media Composer is re-read. Loaded objects are shared between tabs and treated
as read-only by every report.
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from dataclasses import dataclass

from . import progress
from .captions import CaptionDoc
from .models import Timeline
from .parsers import ParseError, parse_timeline

_MAX_ENTRIES = 8  # a handful of (file, sequence) loads — enough for the pickers

_lock = threading.Lock()
_cache: "OrderedDict[tuple, _Loaded]" = OrderedDict()


@dataclass
class _Loaded:
    """Everything one load produced. Either half may be an error, kept so a
    later request for it re-raises rather than re-parsing the same file."""

    timeline: Timeline | Exception
    captions: CaptionDoc | Exception | None  # None: not a bin, no captions here


def load_timeline(path: str, sequence_key: int | None = None) -> Timeline:
    """The parsed :class:`Timeline` for *path* (shared, read-only)."""
    return _raise_or(_load(path, sequence_key).timeline)


def load_captions(path: str, sequence_key: int | None = None) -> CaptionDoc:
    """The SubCap :class:`CaptionDoc` read from the bin at *path*."""
    doc = _load(path, sequence_key).captions
    if doc is None:
        raise ParseError(f"{os.path.basename(path)} is not an Avid bin.")
    return _raise_or(doc)


def clear() -> None:
    with _lock:
        _cache.clear()


def _raise_or(value):
    if isinstance(value, Exception):
        raise value
    return value


def _key(path: str, sequence_key: int | None) -> tuple:
    try:
        st = os.stat(path)
        stamp: tuple = (st.st_size, st.st_mtime_ns)
    except OSError:
        stamp = ()  # missing / unreadable: the parse itself reports the error
    return (os.path.abspath(path), stamp, sequence_key)


def _load(path: str, sequence_key: int | None) -> _Loaded:
    key = _key(path, sequence_key)
    # Holding the lock across the parse is what de-duplicates the tabs' racing
    # requests: the parse is CPU-bound Python, so nothing is lost by serialising.
    with _lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
            return hit
        loaded = _parse(path, sequence_key)
        _cache[key] = loaded
        while len(_cache) > _MAX_ENTRIES:
            _cache.popitem(last=False)
        return loaded


def _parse(path: str, sequence_key: int | None) -> _Loaded:
    if os.path.splitext(path)[1].lower() != ".avb":
        try:
            return _Loaded(timeline=parse_timeline(path, sequence_key), captions=None)
        except ParseError as exc:
            return _Loaded(timeline=exc, captions=None)

    # Bins: one open serves both parses. Imported here so pyavb is only needed
    # when a bin is actually loaded.
    from .captions_avb import parse_captions_open
    from .parsers.avb_parser import open_bin, parse_open

    timeline: Timeline | Exception
    captions: CaptionDoc | Exception
    prog = progress.Progress(path)  # drives the drop zones' loading bar
    try:
        with open_bin(path, prog) as f:
            timeline = _wrap(lambda: parse_open(f, path, sequence_key, prog), path)
            captions = _wrap(lambda: parse_captions_open(f, path, sequence_key), path)
    except Exception as exc:  # noqa: BLE001 - the open itself failed
        err = _as_parse_error(exc, path)
        timeline = captions = err
    prog.set(1.0)
    return _Loaded(timeline=timeline, captions=captions)


def _wrap(fn, path: str):
    """Run one parse, turning any crash into the ParseError the UI expects
    (mirroring :func:`parsers.parse_timeline`)."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        return _as_parse_error(exc, path)


def _as_parse_error(exc: Exception, path: str) -> ParseError:
    if isinstance(exc, ParseError):
        return exc
    err = ParseError(f"Could not read {os.path.basename(path)}: {exc}")
    err.__cause__ = exc
    return err

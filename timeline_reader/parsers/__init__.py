"""Parser dispatch.

Given a path, pick the right parser by extension and hand back a
:class:`~timeline_reader.models.Timeline`. Every parser raises
:class:`ParseError` with a human-readable message on failure so the UI can
show something useful.
"""

from __future__ import annotations

import os

from ..models import Timeline


class ParseError(Exception):
    """Raised when a file cannot be parsed into a Timeline."""


# Extensions we can turn into a Timeline (for the clip list / opticals list).
TIMELINE_EXTENSIONS = {".avb", ".edl", ".aaf", ".txt", ".tsv", ".tab"}


def parse_timeline(path: str, sequence_key: int | None = None) -> Timeline:
    """Parse *path* into a Timeline, dispatching on file extension.

    ``sequence_key`` selects which sequence to read from a multi-sequence
    source (bin / AAF); it is ignored by single-sequence formats.
    """
    ext = os.path.splitext(path)[1].lower()
    # Imported lazily so a missing optional dep only breaks its own format.
    if ext == ".avb":
        from .avb_parser import parse as p
        takes_key = True
    elif ext == ".edl":
        from .edl_parser import parse as p
        takes_key = False
    elif ext == ".aaf":
        from .aaf_parser import parse as p
        takes_key = True
    elif ext in (".txt", ".tsv", ".tab"):
        from .tab_parser import parse as p
        takes_key = False
    else:
        raise ParseError(f"Unsupported file type: {ext or path!r}")
    try:
        return p(path, sequence_key) if takes_key else p(path)
    except ParseError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface any parser crash cleanly
        raise ParseError(f"Could not read {os.path.basename(path)}: {exc}") from exc

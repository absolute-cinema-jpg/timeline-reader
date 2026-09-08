"""Spreadsheet writers (CSV / TSV) and plain-text writer for SRT."""

from __future__ import annotations

import csv
import io


def rows_to_delimited(headers: list[str], rows: list[list[str]], delimiter: str = ",") -> str:
    """Serialise a table to a delimited string (CSV or TSV)."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=delimiter, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(headers)
    writer.writerows(rows)
    return buf.getvalue()


def write_delimited(path: str, headers: list[str], rows: list[list[str]], delimiter: str = ",") -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=delimiter, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headers)
        writer.writerows(rows)


def write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def delimiter_for(path: str) -> str:
    return "\t" if path.lower().endswith((".tsv", ".tab", ".txt")) else ","

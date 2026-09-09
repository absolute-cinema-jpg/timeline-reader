"""Table writers: CSV / TSV / Excel (.xlsx) / OpenDocument (.ods), and SRT text.

The UI shares one list of export formats (:data:`EXPORT_FORMATS`) and one
dispatcher (:func:`export_table`) so every report tab offers the same choices
and stays consistent. All cell values are written as text, preserving timecodes,
leading zeros and clip names exactly as shown in the app.
"""

from __future__ import annotations

import csv
import io

# (combo label, file extension, file-dialog filter, kind)
EXPORT_FORMATS: list[tuple[str, str, str, str]] = [
    ("CSV (.csv)", ".csv", "CSV (*.csv)", "csv"),
    ("TSV (.tsv)", ".tsv", "TSV (*.tsv)", "tsv"),
    ("Excel (.xlsx)", ".xlsx", "Excel workbook (*.xlsx)", "xlsx"),
    ("OpenDocument (.ods)", ".ods", "OpenDocument spreadsheet (*.ods)", "ods"),
]


def format_labels() -> list[str]:
    return [f[0] for f in EXPORT_FORMATS]


def format_at(index: int) -> tuple[str, str, str, str]:
    """Format spec for a combo index (clamped to a valid entry)."""
    index = index if 0 <= index < len(EXPORT_FORMATS) else 0
    return EXPORT_FORMATS[index]


# --------------------------------------------------------------------------- #
# Dispatcher
# --------------------------------------------------------------------------- #
def export_table(path: str, headers: list[str], rows: list[list[str]], kind: str,
                 sheet_name: str = "Report") -> None:
    if kind == "csv":
        write_delimited(path, headers, rows, ",")
    elif kind == "tsv":
        write_delimited(path, headers, rows, "\t")
    elif kind == "xlsx":
        write_xlsx(path, headers, rows, sheet_name)
    elif kind == "ods":
        write_ods(path, headers, rows, sheet_name)
    else:
        raise ValueError(f"Unknown export format: {kind!r}")


# --------------------------------------------------------------------------- #
# Delimited (CSV / TSV) and plain text
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Sheet helpers
# --------------------------------------------------------------------------- #
def _safe_sheet_name(name: str) -> str:
    """A worksheet name valid for Excel: no []:*?/\\ and at most 31 chars."""
    cleaned = "".join("_" if ch in "[]:*?/\\" else ch for ch in (name or "")).strip()
    return (cleaned or "Report")[:31]


# --------------------------------------------------------------------------- #
# Excel (.xlsx) — openpyxl
# --------------------------------------------------------------------------- #
def write_xlsx(path: str, headers: list[str], rows: list[list[str]], sheet_name: str = "Report") -> None:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Excel export needs the 'openpyxl' package.") from exc

    wb = Workbook()
    ws = wb.active
    ws.title = _safe_sheet_name(sheet_name)

    ws.append([str(h) for h in headers])
    for row in rows:
        ws.append([str(v) for v in row])

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="2A2A2A")
    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center")

    ws.freeze_panes = "A2"
    if headers:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(rows) + 1}"
        for col, head in enumerate(headers, 1):
            width = len(str(head))
            for row in rows:
                if col - 1 < len(row):
                    width = max(width, len(str(row[col - 1])))
            ws.column_dimensions[get_column_letter(col)].width = min(max(width + 2, 8), 46)

    wb.save(path)


# --------------------------------------------------------------------------- #
# OpenDocument spreadsheet (.ods) — odfpy
# --------------------------------------------------------------------------- #
def write_ods(path: str, headers: list[str], rows: list[list[str]], sheet_name: str = "Report") -> None:
    try:
        from odf.opendocument import OpenDocumentSpreadsheet
        from odf.style import Style, TableCellProperties, TextProperties
        from odf.table import Table, TableCell, TableRow
        from odf.text import P
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("OpenDocument export needs the 'odfpy' package.") from exc

    doc = OpenDocumentSpreadsheet()
    header_style = Style(name="Header", family="table-cell")
    header_style.addElement(TextProperties(fontweight="bold"))
    header_style.addElement(TableCellProperties(backgroundcolor="#2a2a2a"))
    doc.automaticstyles.addElement(header_style)

    table = Table(name=_safe_sheet_name(sheet_name))

    header_row = TableRow()
    for head in headers:
        cell = TableCell(valuetype="string", stylename=header_style)
        cell.addElement(P(text=str(head)))
        header_row.addElement(cell)
    table.addElement(header_row)

    for row in rows:
        tr = TableRow()
        for value in row:
            cell = TableCell(valuetype="string")
            cell.addElement(P(text=str(value)))
            tr.addElement(cell)
        table.addElement(tr)

    doc.spreadsheet.addElement(table)
    doc.save(path)

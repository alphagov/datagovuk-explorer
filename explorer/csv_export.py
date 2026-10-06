"""CSV export plumbing shared by the page downloads.

Every export is the page's own filtered, sorted query run without its
LIMIT/OFFSET (see queries/core.py's all_rows) — the view builds the same
statement for the page and the export, so the file can't drift from the
table it came from. Dates serialise to ISO, None to an empty cell, and a
UTF-8 BOM is written so Excel reads non-ASCII names correctly.
"""

import csv
import io
from collections.abc import Callable, Iterable
from datetime import date, datetime

from django.http import HttpResponse


def serialize(value):
    """A cell value as CSV text: dates/times to ISO, None to "", else as-is
    (numbers are stringified by the csv writer)."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None:
        return ""
    return value


def _default_cell(row: dict, key: str):
    return serialize(row.get(key))


def csv_response(
    filename: str,
    columns: list[tuple[str, str]],
    rows: Iterable[dict],
    cell: Callable[[dict, str], object] = _default_cell,
) -> HttpResponse:
    """One downloadable CSV attachment for (header, key) columns and row
    dicts. `cell` resolves each cell — the default looks the key up in the
    row and serialises dates; a caller with fallback columns passes its own.
    """
    buffer = io.StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer)
    writer.writerow([header for header, _ in columns])
    for row in rows:
        writer.writerow([cell(row, key) for _, key in columns])
    response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response

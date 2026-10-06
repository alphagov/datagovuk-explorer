"""CSV export plumbing shared by the report and publisher downloads.

Every export is the page's own filtered, sorted query run without its
LIMIT/OFFSET — the view rebuilds the same statement and passes
CSV_ROW_LIMIT, so the file can't drift from the table it came from. Dates
serialise to ISO, None to an empty cell, and a UTF-8 BOM is written so
Excel reads non-ASCII names correctly.
"""

import csv
import io
from collections.abc import Callable, Iterable
from datetime import date, datetime

from django.http import HttpResponse

# Effectively "all rows": the list statements all end in LIMIT %s OFFSET %s,
# so an export passes this limit and offset 0. The largest table here is well
# under it.
CSV_ROW_LIMIT = 1_000_000


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

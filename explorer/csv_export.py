"""CSV export plumbing shared by the page downloads.

Every export is the page's own filtered, sorted query run without its
LIMIT/OFFSET (see queries/core.py's iter_rows) — the view builds the same
statement for the page and the export, so the file can't drift from the
table it came from. Dates serialise to ISO, None to an empty cell, and a
UTF-8 BOM is written so Excel reads non-ASCII names correctly.

The response streams: iter_rows pulls rows from a server-side cursor and
csv_response yields the file in chunks, so a 200k-row export never holds the
whole file (or its rows) in memory.
"""

import csv
import io
from collections.abc import Callable, Iterable, Iterator
from datetime import date, datetime

from django.http import StreamingHttpResponse

# Flush a chunk once the buffer is this big. One write per ~64 KiB rather
# than one per row: 200k tiny WSGI writes would dominate the run time.
_STREAM_CHUNK = 64 * 1024


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


def _csv_chunks(columns: list[tuple[str, str]], rows: Iterable[dict], cell: Callable) -> Iterator[str]:
    """Yield the CSV as text chunks: BOM + header row first, then data rows,
    flushing the buffer to the response every _STREAM_CHUNK bytes so nothing
    larger than one chunk is ever held."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    buffer.write("\ufeff")
    writer.writerow([header for header, _ in columns])
    for row in rows:
        writer.writerow([cell(row, key) for _, key in columns])
        if buffer.tell() >= _STREAM_CHUNK:
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)
    remainder = buffer.getvalue()
    if remainder:
        yield remainder


def csv_response(
    filename: str,
    columns: list[tuple[str, str]],
    rows: Iterable[dict],
    cell: Callable[[dict, str], object] = _default_cell,
) -> StreamingHttpResponse:
    """One downloadable CSV attachment for (header, key) columns and row
    dicts, streamed. `rows` is any iterable of row dicts — pass the lazy
    queries/core.iter_rows so the export never materialises. `cell` resolves
    each cell — the default looks the key up in the row and serialises dates;
    a caller with fallback columns passes its own.
    """
    response = StreamingHttpResponse(_csv_chunks(columns, rows, cell), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response

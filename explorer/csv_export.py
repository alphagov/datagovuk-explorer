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
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import UTC, date, datetime

from django.http import StreamingHttpResponse
from django.utils.text import slugify

# Flush a chunk once the buffer is this big. One write per ~64 KiB rather
# than one per row: 200k tiny WSGI writes would dominate the run time.
_STREAM_CHUNK = 64 * 1024

# Cap the descriptive part of an export name so a long filter list (or a long
# slug) can't push the date / .csv off the end.
_FILENAME_MAX = 120


def _slug(value) -> str:
    """ASCII slug for a filename part — hyphens instead of the underscores
    slugify keeps, so codes like NOT_FOUND read as "not-found"."""
    return slugify(str(value)).replace("_", "-").strip("-")


def csv_filename(base: str, filters: Mapping | None = None, *, on: date | None = None) -> str:
    """A descriptive CSV attachment name: the page's base slug, each active
    filter as "<key>-<slug>", then the date — e.g.
    "link-status-category-not-found-2026-06-14.csv".

    Pass the view's *validated* filters (the resolver's output, not raw GET),
    so ignored junk never reaches the header. Values are slugified to ASCII,
    so a data-derived filter (a host, a publisher slug) can't break the
    Content-Disposition quoted string. Falsy values are skipped; key order
    follows the mapping (each view builds its filters in a fixed order).
    """
    parts = [_slug(base) or "export"]
    for key, value in (filters or {}).items():
        if value in (None, "", (), [], {}):
            continue
        slug = _slug(value)
        if slug:
            parts.append(f"{_slug(key)}-{slug}")
    stamp = (on or datetime.now(UTC).date()).isoformat()
    stem = "-".join(parts)
    # Cap the descriptive part only, keeping the date and extension intact.
    room = _FILENAME_MAX - len(stamp) - len(".csv") - 1
    if len(stem) > room:
        stem = stem[:room].rstrip("-")
    return f"{stem}-{stamp}.csv"


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

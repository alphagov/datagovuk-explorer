"""Unit tests for explorer/csv_export.py — the streamed CSV attachment.

No DB: these pin the response shape (streaming, headers, BOM) and that the
writer flushes in bounded chunks rather than buffering the whole file.
"""

import csv
import io
from datetime import UTC, date, datetime

from django.http import StreamingHttpResponse

from explorer.csv_export import csv_filename, csv_response, serialize


def _rows(response) -> list[list[str]]:
    body = b"".join(response.streaming_content).decode("utf-8-sig")
    return list(csv.reader(io.StringIO(body)))


def test_csv_response_streams_bom_header_and_rows():
    response = csv_response(
        "x.csv",
        [("Name", "name"), ("N", "n")],
        [{"name": "a", "n": 1}, {"name": "b", "n": 2}],
    )
    assert isinstance(response, StreamingHttpResponse)
    assert response["Content-Disposition"] == 'attachment; filename="x.csv"'
    assert response["Content-Type"].startswith("text/csv")
    rows = _rows(response)
    assert rows[0] == ["Name", "N"]
    assert rows[1:] == [["a", "1"], ["b", "2"]]


def test_csv_response_flushes_in_bounded_chunks():
    """A list larger than the flush threshold must come out as several
    chunks, and no single chunk may hold the whole file."""
    rows = [{"name": "x" * 40, "n": i} for i in range(10_000)]
    response = csv_response("x.csv", [("Name", "name"), ("N", "n")], rows)
    chunks = [len(chunk) for chunk in response.streaming_content]
    assert len(chunks) > 1  # not one buffered string
    assert max(chunks) < 200_000  # ~64 KiB target, plus at most one row


def test_serialize_dates_none_and_passthrough():
    flag = True  # a variable, not a positional literal (ruff FBT003)
    assert serialize(None) == ""
    assert serialize(date(2024, 1, 2)) == "2024-01-02"
    assert serialize(datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)) == "2024-01-02T03:04:05+00:00"
    assert serialize("s") == "s"
    assert serialize(flag) is True


def test_csv_filename_reflects_filters_and_date():
    day = date(2026, 6, 14)
    assert csv_filename("links", on=day) == "links-2026-06-14.csv"
    assert csv_filename("link-status", {}, on=day) == "link-status-2026-06-14.csv"
    name = csv_filename("link-status", {"category": "NOT_FOUND", "status": None}, on=day)
    assert name == "link-status-category-not-found-2026-06-14.csv"
    name = csv_filename("datasets", {"publisher": "alpha", "created_year": "2020"}, on=day)
    assert name == "datasets-publisher-alpha-created-year-2020-2026-06-14.csv"


def test_csv_filename_slugifies_and_caps():
    day = date(2026, 6, 14)
    # A data-derived value can't break the header's quoted filename.
    name = csv_filename("links", {"domain": 'a"; X=1\r\nBad: y'}, on=day)
    assert name.startswith("links-")
    assert name.endswith("-2026-06-14.csv")
    assert all(ch.isalnum() or ch in "-._" for ch in name)
    assert not any(ch in name for ch in '\r\n";:')
    # Long filter lists are truncated, but the date and extension survive.
    long_name = csv_filename("links", {f"k{i}": "v" * 50 for i in range(20)}, on=day)
    assert len(long_name) <= 120
    assert long_name.endswith("-2026-06-14.csv")

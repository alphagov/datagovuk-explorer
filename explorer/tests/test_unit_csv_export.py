"""Unit tests for explorer/csv_export.py — the streamed CSV attachment.

No DB: these pin the response shape (streaming, headers, BOM) and that the
writer flushes in bounded chunks rather than buffering the whole file.
"""

import csv
import io
from datetime import UTC, date, datetime

from django.http import StreamingHttpResponse

from explorer.csv_export import csv_response, serialize


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

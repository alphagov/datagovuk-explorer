"""Shared CSV-download test helper — one reader for every page's export.

Not a test module (no `test_` prefix), so pytest won't collect it.
"""

import csv
import io
from datetime import UTC, datetime


def today_iso() -> str:
    """Today's date as csv_export names files — matched here so the download
    tests can build the expected Content-Disposition deterministically."""
    return datetime.now(UTC).date().isoformat()


def csv_rows(response) -> list[list[str]]:
    """A download response's rows as lists, header row included.

    Exports are streamed (StreamingHttpResponse), so the body is consumed
    from streaming_content; a plain HttpResponse's .content is used as-is.
    """
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    if getattr(response, "streaming", False):
        body = b"".join(response.streaming_content).decode("utf-8-sig")
    else:
        body = response.content.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(body)))

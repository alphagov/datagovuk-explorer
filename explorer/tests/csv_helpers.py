"""Shared CSV-download test helper — one reader for every page's export.

Not a test module (no `test_` prefix), so pytest won't collect it.
"""

import csv
import io


def csv_rows(response) -> list[list[str]]:
    """A download response's rows as lists, header row included."""
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    return list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))

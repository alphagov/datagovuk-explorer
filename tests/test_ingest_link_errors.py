"""Unit tests for scripts/ingest_link_errors.py (offline — no DB).

Covers the deterministic parts:
- parse_row: http-status '' -> None and int casting, to-delete -> bool,
  every other column kept as-is
- load_rows: quoted fields (commas inside quotes), all rows kept (no
  filtering — OK rows and both check runs are part of the story), a tiny
  fixture CSV end to end
- COLUMNS / CSV_HEADERS stay aligned (insert can never silently reorder)

The write path (TRUNCATE + insert into link_errors, idempotency) is covered
by tests/test_ingest_link_errors_db.py against a scratch migrated database.
Run with: uv run pytest tests/test_ingest_link_errors.py
"""

import csv
import io
import tempfile
from pathlib import Path

import scripts.ingest_link_errors as ile

HEADER = (
    "datagovuk-url,package-id,package-name,package-metadata-created,"
    "package-metadata-modified,guid,resource-id,resource-url,"
    "resource-created,resource-last-modified,resource-metadata-modified,"
    "org-name,org-id,http-status,category,error-detail,to-delete,checked-at"
)


def csv_row(*, status="404", category="NOT_FOUND", to_delete="true", detail="HTTP 404", pkg="p1"):
    """One data CSV row in file order — http-status, category, error-detail
    and to-delete are the fields the casts/quotes exercise."""
    return (
        f"https://www.data.gov.uk/dataset/{pkg}/name,{pkg},name,2010-05-19,2013-08-12,,"
        f"res-{pkg},http://example.com/file.xls,,,,org-a,org-a-1,"
        f'{status},{category},"{detail}",{to_delete},2026-09-02T12:13:02+00:00'
    )


def write_csv(tmp: str, lines: list[str]) -> Path:
    p = Path(tmp) / "errors.csv"
    p.write_text("\n".join([HEADER, *lines]) + "\n", encoding="utf-8")
    return p


def parse_line(line: str) -> dict:
    """One data CSV line as csv.DictReader would hand it to parse_row —
    the real quoting path, not a naive split."""
    return next(csv.DictReader(io.StringIO(HEADER + "\n" + line)))


def test_parse_row_casts():
    # '' http-status (DNS/timeout — no HTTP response) -> None; to-delete bool
    values = ile.parse_row(
        parse_line(csv_row(status="", category="DNS_ERROR", to_delete="false", detail="Name or service not known")),
    )
    assert values["http_status"] is None
    assert values["to_delete"] is False
    assert values["category"] == "DNS_ERROR"
    assert values["error_detail"] == "Name or service not known"
    assert values["checked_at"] == "2026-09-02T12:13:02+00:00"

    # an int http-status parses; to-delete true parses
    values = ile.parse_row(parse_line(csv_row()))
    assert values["http_status"] == 404
    assert values["to_delete"] is True

    # non-typed columns pass through as-is ('' stays '', not NULL)
    row = parse_line(csv_row())
    row["resource-created"] = ""
    values = ile.parse_row(row)
    assert values["resource_created"] == ""
    assert values["package_id"] == "p1"


def test_load_rows_all_rows_and_quoted_fields():
    # A quoted error-detail with a comma (the csv module's job — DictReader
    # must keep it one field), an OK row (kept — no filtering) and a
    # code-less DNS row all land in the parsed stream.
    with tempfile.TemporaryDirectory() as d:
        p = write_csv(
            d,
            [
                csv_row(detail="HTTP 404, second try failed"),
                csv_row(status="200", category="OK", to_delete="false", detail="", pkg="p2"),
                csv_row(status="", category="TIMEOUT", to_delete="true", detail="Timeout", pkg="p3"),
            ],
        )
        rows = list(ile.load_rows(p))
        assert len(rows) == 3  # every row ingested, none filtered
        assert rows[0]["error_detail"] == "HTTP 404, second try failed"  # quoted comma intact
        assert rows[1]["category"] == "OK"
        assert rows[1]["http_status"] == 200
        assert rows[1]["to_delete"] is False
        assert rows[2]["http_status"] is None


def test_csv_header_alignment():
    """COLUMNS and CSV_HEADERS cover the same 18 columns 1:1 — an insert
    can't silently reorder/drop a column."""
    assert len(ile.COLUMNS) == len(set(ile.COLUMNS)) == len(ile.CSV_HEADERS)
    assert set(ile.COLUMNS) == set(ile.CSV_HEADERS)
    assert set(ile.CSV_HEADERS.values()) == set(HEADER.split(","))
    # csv.DictReader on the real header yields exactly the mapped keys
    with tempfile.TemporaryDirectory() as d:
        p = write_csv(d, [csv_row()])
        with p.open(newline="", encoding="utf-8") as f:
            fieldnames = set(csv.DictReader(f).fieldnames)
    assert fieldnames == set(ile.CSV_HEADERS.values())


def test_load_rows_missing_file():
    with tempfile.TemporaryDirectory() as d:
        missing = Path(d) / "nope.csv"
        try:
            list(ile.load_rows(missing))
        except FileNotFoundError:
            pass
        else:
            raise AssertionError("load_rows on a missing file must raise FileNotFoundError")

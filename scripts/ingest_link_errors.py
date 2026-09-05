#!/usr/bin/env python3
"""Load data/errors-current.csv into the `link_errors` table.

The CSV is the link checker's full output for every resource link across
the catalogue — not only errors: `category = OK` rows are links that
failed an earlier check and pass now (the "resolved" population the
/links/errors report shows as OK). The table keeps every row as-is — no
filtering, no dedup — so a resource whose status changed between check
runs appears once per run.

Idempotent: TRUNCATEs `link_errors` then reloads (like ingest_reviews.py)
— run it after a new checker output lands. The file is read regardless of
git state; committing data/errors-current.csv is the user's call.

Usage: python -m scripts.ingest_link_errors [--file data/errors-current.csv]
       DATABASE_URL=postgresql://localhost:5432/other python -m scripts.ingest_link_errors
"""

import csv
import sys
from collections.abc import Iterator
from pathlib import Path

from scripts.db import connect, database_url

DEFAULT_FILE = Path(__file__).resolve().parent.parent / "data" / "errors-current.csv"

# Insert columns in table order (datagovuk_url first — a CSV-derived column
# kept so the report can link out when the package is absent from the
# datasets snapshot). Keyed by their CSV header names below.
COLUMNS = [
    "datagovuk_url",
    "package_id",
    "package_name",
    "package_metadata_created",
    "package_metadata_modified",
    "guid",
    "resource_id",
    "resource_url",
    "resource_created",
    "resource_last_modified",
    "resource_metadata_modified",
    "org_name",
    "org_id",
    "http_status",
    "category",
    "error_detail",
    "to_delete",
    "checked_at",
]

# Column name -> CSV header
CSV_HEADERS = {
    "datagovuk_url": "datagovuk-url",
    "package_id": "package-id",
    "package_name": "package-name",
    "package_metadata_created": "package-metadata-created",
    "package_metadata_modified": "package-metadata-modified",
    "guid": "guid",
    "resource_id": "resource-id",
    "resource_url": "resource-url",
    "resource_created": "resource-created",
    "resource_last_modified": "resource-last-modified",
    "resource_metadata_modified": "resource-metadata-modified",
    "org_name": "org-name",
    "org_id": "org-id",
    "http_status": "http-status",
    "category": "category",
    "error_detail": "error-detail",
    "to_delete": "to-delete",
    "checked_at": "checked-at",
}


def parse_row(row: dict) -> dict:
    """One csv.DictReader row -> the insert values dict, with the two typed
    casts the schema needs:

    - http-status: '' (DNS/timeout/connection rows that never got an HTTP
      response) -> None; otherwise the int code.
    - to-delete: 'true'/'false' -> bool.

    Every other column is kept as-is ('' stays '', preserving the CSV byte
    for byte — the schema columns are nullable text for a reason).
    """
    values = {col: row[CSV_HEADERS[col]] for col in COLUMNS}
    status = (row.get("http-status") or "").strip()
    values["http_status"] = int(status) if status else None
    values["to_delete"] = (row.get("to-delete") or "").strip().lower() == "true"
    return values


def load_rows(path: Path) -> Iterator[dict]:
    """Every row in the CSV, parsed (no filtering, no dedup — the report
    ingests the file as-is). csv.DictReader handles quoted commas and
    quoted fields; blank lines are skipped by the reader."""
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            yield parse_row(row)


def ingest(db, rows: Iterator[dict]) -> int:
    """Truncate + insert every parsed row; returns the row count."""
    count = 0

    def _run(tx) -> None:
        nonlocal count
        tx.exec("TRUNCATE link_errors RESTART IDENTITY")
        stmt = tx.prepare(
            "INSERT INTO link_errors (" + ", ".join(COLUMNS) + ") VALUES (" + ", ".join("?" for _ in COLUMNS) + ")",
        )
        for values in rows:
            stmt.run(*[values[col] for col in COLUMNS])
            count += 1

    db.transaction(_run)
    return count


def main(file: str = str(DEFAULT_FILE)) -> None:
    path = Path(file)
    if not path.exists():
        print(f"No file at {path} — nothing to do.", file=sys.stderr)
        sys.exit(1)

    # Count rows up front (a second read) so the summary is accurate even
    # when ingest fails mid-insert and the transaction rolls back.
    rows = load_rows(path)
    total = sum(1 for _ in load_rows(path))

    db = connect(database_url())
    try:
        n = ingest(db, rows)
    finally:
        db.close()
    print(f"Inserted {n} row(s) into link_errors from {path.name} ({total} read).")


if __name__ == "__main__":
    try:
        main(*sys.argv[1:])
    except (RuntimeError, ValueError, OSError, KeyError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

"""Expand temporal_periods into the dataset_years summary table.

Reads temporal_periods (populated by ingest_ckan.py) and expands each
[from_year, to_year] range into one row per (dataset_id, year), clamped
to 1900-2100. Used by the temporal facet instead of generate_series at
request time.

Idempotent: TRUNCATE + INSERT (the populate function handles its own
TRUNCATE), so re-running is always safe.

Usage: python -m scripts.build_dataset_years
"""

from scripts.db import connect, database_url

DATABASE_URL = database_url()

INSERT_DATASET_YEARS_SQL = """
INSERT INTO dataset_years (dataset_id, year)
SELECT DISTINCT tp.dataset_id, yrs.y
FROM temporal_periods tp
CROSS JOIN LATERAL (
    SELECT generate_series(
        GREATEST(COALESCE(tp.from_year, tp.to_year), 1900),
        LEAST(COALESCE(tp.to_year, tp.from_year), 2100)
    ) AS y
) yrs
WHERE GREATEST(COALESCE(tp.from_year, tp.to_year), 1900)
      <= LEAST(COALESCE(tp.to_year, tp.from_year), 2100)
"""


def _populate_dataset_years(db) -> int:
    """Expand temporal_periods into dataset_years. Returns the row count."""
    db.exec("TRUNCATE TABLE dataset_years")
    db.exec(INSERT_DATASET_YEARS_SQL)
    row = db.prepare("SELECT COUNT(*) AS n FROM dataset_years").get()
    return row["n"]


def main() -> None:
    """Rebuild the dataset_years table (TRUNCATE + INSERT).

    Expands temporal_periods ranges into one row per (dataset, year).
    Runs in seconds against the existing temporal_periods data — use this
    after a full build or whenever temporal_periods changes."""

    db = connect(DATABASE_URL)
    try:
        n = _populate_dataset_years(db)
        print(f"dataset_years: {n} rows")
    finally:
        db.close()


if __name__ == "__main__":
    main()

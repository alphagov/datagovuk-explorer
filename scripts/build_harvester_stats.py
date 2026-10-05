"""Populate denormalised stats columns on harvest_sources.

Promotes two computed values to real columns so /harvesters queries read
them directly rather than joining and extracting JSON on every request:

  dataset_count — number of datasets whose harvest_source_id = h.id
  last_run      — last_harvest_request from the json status block

Run after build_db (datasets must be loaded before dataset_count is accurate).
Safe to re-run: both columns are overwritten unconditionally.

Usage: python -m scripts.build_harvester_stats
       DATABASE_URL=postgresql://... python -m scripts.build_harvester_stats
"""

import sys

from scripts.db import connect, database_url


def build(db) -> int:
    """Populate dataset_count and last_run on all harvest_sources rows.
    Returns the number of rows updated."""
    db.exec(
        """
        UPDATE harvest_sources
           SET dataset_count = (
                   SELECT COUNT(*)
                     FROM datasets
                    WHERE harvest_source_id = harvest_sources.id
               ),
               last_run = NULLIF(
                   json::jsonb -> 'status' ->> 'last_harvest_request',
                   'None'
               )
        """,
    )
    row = db.prepare("SELECT COUNT(*) AS n FROM harvest_sources").get()
    return row["n"]


def main() -> None:
    db = connect(database_url())
    try:
        print("Populating harvest_sources stats columns...", file=sys.stderr)
        n = build(db)
        print(f"  {n} harvest sources updated", file=sys.stderr)
    finally:
        db.close()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

#!/usr/bin/env python3
"""Export the reviews/suggestions DB rows back to per-dataset JSON files.

The file-based LLM pipeline (scripts/llm/review.py + suggest.py) and the DB
can drift: the DB may hold rows restored from a production dump while
downloads/reviews and downloads/suggestions are empty. Because
ingest_reviews / ingest_suggestions TRUNCATE + reload from files, generating
files for only a subset (e.g. the new datasets) and then ingesting would drop
every DB row that has no file.

This script writes each stored record back to the canonical layout
(downloads/reviews/<org>/ and downloads/suggestions/<org>/) so the next
`review`/`suggest` run skips them and the ingest is lossless. The record JSON
in the DB is exactly what the pipeline wrote to disk, so the files round-trip.

Reviews and suggestions live in separate directories and separate files — the
old combined scripts/review_suggest.py was split in commit f8ad2c0 (schema
migration 0003_split_review_suggestion).

Usage:
  python -m scripts.llm.export_records                 # skip existing files
  python -m scripts.llm.export_records --force         # overwrite existing
  python -m scripts.llm.export_records --out-dir downloads
"""

import argparse
import json
import sys
from pathlib import Path

from scripts.db import connect, database_url
from scripts.llm.common import record_path, write_record

DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent.parent / "downloads"

# (table, subdirectory under out_dir) — both are stored split, one file each.
_TABLES = (("reviews", "reviews"), ("suggestions", "suggestions"))


def export_table(db, table: str, out_dir: Path, *, overwrite: bool) -> tuple[int, int]:
    """Write every stored record under out_dir/<table>.

    Returns (written, skipped). A row whose file already exists is skipped
    unless overwrite is set, so an export can't clobber newer local files.
    """
    rows = db.prepare(f"SELECT json FROM {table} ORDER BY dataset_ckan_id").all()
    written = skipped = 0
    for row in rows:
        try:
            record = json.loads(row["json"])
        except (TypeError, ValueError):
            continue
        if not record.get("dataset_id"):
            continue
        if not overwrite and record_path(out_dir / table, record).exists():
            skipped += 1
            continue
        write_record(out_dir / table, record)
        written += 1
    return written, skipped


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="downloads root (default: downloads/)")
    parser.add_argument("--force", action="store_true", help="overwrite files that already exist")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    db = connect(database_url())
    try:
        for table, subdir in _TABLES:
            written, skipped = export_table(db, table, args.out_dir, overwrite=args.force)
            print(
                f"{subdir}: wrote {written}, skipped {skipped} existing (under {args.out_dir / table})",
                file=sys.stderr,
            )
    finally:
        db.close()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError, KeyError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

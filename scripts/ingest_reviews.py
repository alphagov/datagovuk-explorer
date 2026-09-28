#!/usr/bin/env python3
"""Load per-dataset review JSON files into the `reviews` table.

The pipeline (review_suggest.py) writes one JSON file per dataset under
downloads/reviews/<org>/; this script (re)populates the DB table the web
app reads.

Idempotent: TRUNCATEs `reviews` then reloads — run it after any
review_suggest run to refresh the site. Failed (ok:false) records are
kept in the table with their flag; the views filter ok = true at query
time.

Usage: python -m scripts.ingest_reviews [--dir downloads/reviews]
       DATABASE_URL=postgresql://localhost:5432/other python -m scripts.ingest_reviews
"""

import json
import sys
from pathlib import Path

from scripts.db import connect, database_url

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "downloads" / "reviews"


def load_records(directory: Path) -> list[dict]:
    """All review records from per-dataset JSON files; corrupt files skipped."""
    records: list[dict] = []
    if not directory.exists():
        return records
    for f in sorted(directory.rglob("*.json")):
        try:
            records.append(json.loads(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return records


def _scores(r: dict) -> dict:
    """The two sub-scores, or {} when scores is missing/malformed."""
    scores = r.get("scores")
    return scores if isinstance(scores, dict) else {}


def _subscore(r: dict, key: str):
    sub = _scores(r).get(key)
    if not isinstance(sub, dict):
        return None
    score = sub.get("score")
    return score if isinstance(score, int) else None


def _int(v):
    return v if isinstance(v, int) else None


def ingest(db, records: list[dict]) -> int:
    """Truncate + insert records whose dataset exists locally; returns inserted count."""
    ids = [r["dataset_id"] for r in records]
    existing = {str(row["id"]) for row in db.prepare("SELECT id FROM datasets WHERE id = ANY(?)").all(ids)}
    present = [r for r in records if r["dataset_id"] in existing]
    skipped = len(records) - len(present)
    if skipped:
        print(f"Skipped {skipped} review(s) — dataset not in local DB.")

    def _run(tx) -> None:
        tx.exec("TRUNCATE reviews RESTART IDENTITY")
        stmt = tx.prepare(
            """INSERT INTO reviews
               (id, dataset_id, ok, findability, resources,
                theme, tags, title, "desc", theme_confidence, created_at, json)
               VALUES (DEFAULT, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        )
        for r in present:
            stmt.run(
                r["dataset_id"],
                bool(r.get("ok")),
                _subscore(r, "title-description"),
                _subscore(r, "resources"),
                r.get("suggested_theme"),
                json.dumps(r["suggested_tags"], ensure_ascii=False) if r.get("suggested_tags") else None,
                r.get("suggested_title"),
                r.get("suggested_description"),
                r.get("suggested_theme_confidence"),
                r.get("reviewed_at"),
                json.dumps(r, ensure_ascii=False),
            )

    db.transaction(_run)
    return len(present)


def main(directory: str = str(DEFAULT_DIR)) -> None:
    path = Path(directory)
    records = load_records(path)
    if not records:
        print(f"No review files in {path} — nothing to do.", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(records)} review(s) from {path}.")

    db = connect(database_url())
    try:
        n = ingest(db, records)
    finally:
        db.close()
    print(f"Inserted {n} row(s) into reviews.")


if __name__ == "__main__":
    try:
        main(*sys.argv[1:])
    except (RuntimeError, ValueError, OSError, KeyError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

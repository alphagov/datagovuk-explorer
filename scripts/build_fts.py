"""Populate the tags and fts (tsvector) columns on the datasets table.

Reads each dataset row + its raw JSON from dataset_json, extracts tags from
the JSON, and updates tags + fts in batches. The GIN index on fts
(idx_datasets_fts) is migration-owned (0001) and pre-exists — this script
populates the column the index covers.

Idempotent: re-running updates every row from the current dataset_json data,
so it is always safe to rerun.

Usage: python -m scripts.build_fts
"""

import json
import re
import sys
from functools import partial

from scripts.db import connect, database_url

DATABASE_URL = database_url()

_WS_RE = re.compile(r"\s+")

_FETCH_SQL = """
SELECT d.id, d.title, d.notes, dj.json
FROM datasets d
JOIN dataset_json dj ON dj.dataset_id = d.id
ORDER BY d.id
"""

_UPDATE_FTS_SQL = """
UPDATE datasets
SET tags = ?, fts = to_tsvector(
    'english',
    coalesce(?, '') || ' ' || coalesce(?, '') || ' ' || coalesce(?, '')
)
WHERE id = ?
"""

_BATCH_SIZE = 5000


def _tags_from_json(raw: dict) -> str:
    """Extract display_name/name tags from the raw dataset JSON, space-joined."""
    return " ".join(
        t
        for t in (
            _WS_RE.sub(" ", (tag.get("display_name") or tag.get("name") or "")).strip()
            for tag in (raw.get("tags") or [])
        )
        if t
    )


def _fts_batch_tx(tx, batch: list) -> int:
    """Update tags + fts for one batch. Returns the row count updated."""
    upd = tx.prepare(_UPDATE_FTS_SQL)
    count = 0
    for r in batch:
        raw = r["json"] if isinstance(r["json"], dict) else json.loads(r["json"])
        title = _WS_RE.sub(" ", (r["title"] or "")).strip()
        notes = _WS_RE.sub(" ", (r["notes"] or "")).strip()
        tags = _tags_from_json(raw)
        upd.run(tags, title, notes, tags, r["id"])
        count += 1
    return count


def _populate_fts(db) -> int:
    """Update tags + fts on every dataset row. Returns the row count updated."""
    rows = db.prepare(_FETCH_SQL).all()
    total = 0
    for i in range(0, len(rows), _BATCH_SIZE):
        batch = rows[i : i + _BATCH_SIZE]
        batch_count = db.transaction(partial(_fts_batch_tx, batch=batch))
        total += batch_count
        print(f"  fts: {total} rows...", file=sys.stderr)
    return total


def main() -> None:
    """Rebuild the tags + fts columns from dataset_json (idempotent).

    Reads title/notes from datasets and tags from dataset_json, then
    updates the tags and fts (tsvector) columns in batches. Run after
    ingest_ckan populates datasets and dataset_json."""

    db = connect(DATABASE_URL)
    try:
        n = _populate_fts(db)
        print(f"build_fts: {n} datasets updated")
    finally:
        db.close()


if __name__ == "__main__":
    main()

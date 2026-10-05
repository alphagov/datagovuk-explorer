"""Populate the dataset_content_hash summary table.

Tier-1 exact-duplicate detection: one md5 hash per dataset over its
normalised title, notes and the sorted, deduped set of its resource URLs.
Two datasets with the same hash are byte-for-byte content duplicates
(the harvest-flooding pattern). GROUP BY content_hash HAVING COUNT(*) > 1
finds them in one indexed pass, no self-join.

Reads the existing datasets and links tables (populated by ingest_ckan.py).
Idempotent: TRUNCATE + INSERT, so re-running is always safe.

Usage: python -m scripts.build_dataset_content_hash
"""

from scripts.db import connect, database_url

DATABASE_URL = database_url()

# Computed entirely in SQL rather than a Python loop, both for speed and so
# the normalisation lives in one place. URL normalisation strips the query
# string/fragment and a trailing slash — tracking params shouldn't defeat a match.
INSERT_DATASET_CONTENT_HASH_SQL = r"""
INSERT INTO dataset_content_hash (dataset_id, content_hash)
SELECT
    d.id,
    md5(
        trim(regexp_replace(lower(coalesce(d.title, '')), '\s+', ' ', 'g')) || E'\x1f' ||
        trim(regexp_replace(lower(coalesce(d.notes, '')), '\s+', ' ', 'g')) || E'\x1f' ||
        coalesce(u.urls, '')
    )
FROM datasets d
LEFT JOIN (
    SELECT dataset_id, string_agg(DISTINCT norm_url, E'\x1f' ORDER BY norm_url) AS urls
    FROM (
        SELECT dataset_id, rtrim(regexp_replace(lower(trim(url)), '[?#].*$', ''), '/') AS norm_url
        FROM links
        WHERE url IS NOT NULL AND url != ''
    ) norm
    GROUP BY dataset_id
) u ON u.dataset_id = d.id
"""


def _populate_dataset_content_hash(db) -> int:
    """Populate the dataset_content_hash summary table. Returns the row
    count inserted (one per dataset)."""
    db.exec(INSERT_DATASET_CONTENT_HASH_SQL)
    row = db.prepare("SELECT COUNT(*) AS n FROM dataset_content_hash").get()
    return row["n"]


def main() -> None:
    """Rebuild the dataset_content_hash table (TRUNCATE + INSERT).

    Runs in seconds against the existing datasets/links data — use this
    when tweaking the hash normalisation without a full rebuild."""

    db = connect(DATABASE_URL)
    try:
        db.exec("TRUNCATE TABLE dataset_content_hash")
        n = _populate_dataset_content_hash(db)
        dupes = db.prepare(
            "SELECT COUNT(*) AS n FROM ("
            "  SELECT content_hash FROM dataset_content_hash"
            "  GROUP BY content_hash HAVING COUNT(*) > 1"
            ") sub",
        ).get()["n"]
        print(f"dataset_content_hash: {n} datasets, {dupes} duplicate hash groups")
    finally:
        db.close()


if __name__ == "__main__":
    main()

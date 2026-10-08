"""Pre-compute related-dataset results into lookup tables.

Replaces live pgvector queries at request time with O(1) indexed lookups
for dataset and collection detail pages, and a simple column lookup for
the collections list sort. Run after build-embeddings.

Usage:  uv run --env-file .env python -m scripts.build_related
"""

import sys
import time

from scripts.db import connect, database_url

DATABASE_URL = database_url()

# L2 distance (normalised vectors, so cosine >= ~0.69) below which a
# collection's neighbour counts as "related". Model-dependent: tuned to
# EmbeddingGemma-300M. The BGE model this replaced scored the same pairs at a
# smaller distance — 0.77 was its equivalent. Keep in sync with
# explorer/queries/collections.py (scripts/ and explorer/ can't import each
# other). See docs/collections-datasets-journeys.md.
RELATED_DISTANCE_THRESHOLD = 0.83

# ---- SQL (lateral-join rewrites) ----------------------------------------
# Each pass is a single INSERT…SELECT with a CROSS JOIN LATERAL so
# Postgres controls the iteration — no Python round-trips per dataset.

_TRUNCATE = "TRUNCATE TABLE related_datasets, collection_related_datasets"
_RESET_RELATED_COUNT = "UPDATE collection_pages SET related_count = NULL"

# Semantic: lateral KNN over the HNSW index per dataset embedding.
# ROW_NUMBER outside the lateral so the HNSW ordered scan + LIMIT
# path is unambiguous inside.
_SEMANTIC_LATERAL = """
INSERT INTO related_datasets (dataset_id, related_id, rank, score)
SELECT dataset_id, id,
       ROW_NUMBER() OVER (
           PARTITION BY dataset_id ORDER BY distance, id
       )::int,
       distance
FROM (
    SELECT src.dataset_id, sub.id, sub.distance
    FROM (
        SELECT m.dataset_id, e.embedding
        FROM embedding_map m
        JOIN dataset_embeddings e ON e.rowid = m.rowid
        JOIN datasets d ON d.id = m.dataset_id
        WHERE d.resource_count > 0
    ) src
    CROSS JOIN LATERAL (
        SELECT m2.dataset_id AS id,
               emb2.embedding <-> src.embedding AS distance
        FROM dataset_embeddings emb2
        JOIN embedding_map m2 ON m2.rowid = emb2.rowid
        JOIN datasets d2 ON d2.id = m2.dataset_id
        WHERE m2.dataset_id != src.dataset_id
          AND d2.resource_count > 0
          AND m2.dataset_id NOT IN (
              SELECT sd.dataset_id FROM series_datasets sd
              WHERE sd.series_id IN (
                  SELECT sd2.series_id FROM series_datasets sd2
                  WHERE sd2.dataset_id = src.dataset_id
              )
          )
        ORDER BY emb2.embedding <-> src.embedding, m2.dataset_id
        LIMIT 30
    ) sub
) t
"""

# Collection related datasets: lateral KNN per collection embedding.
_COLLECTION_RELATED_LATERAL = """
INSERT INTO collection_related_datasets (slug, dataset_id, rank, distance)
SELECT slug, id,
       ROW_NUMBER() OVER (
           PARTITION BY slug ORDER BY distance, id
       )::int,
       distance
FROM (
    SELECT ce.slug, sub.id, sub.distance
    FROM collection_embeddings ce
    CROSS JOIN LATERAL (
        SELECT m.dataset_id AS id,
               emb.embedding <-> ce.embedding AS distance
        FROM dataset_embeddings emb
        JOIN embedding_map m ON m.rowid = emb.rowid
        JOIN datasets d ON d.id = m.dataset_id
        WHERE d.resource_count > 0
        ORDER BY emb.embedding <-> ce.embedding, m.dataset_id
        LIMIT 30
    ) sub
) t
"""

# Collection related count: top-500 KNN per collection, count within
# the distance threshold.
_COLLECTION_COUNT_UPDATE = f"""
UPDATE collection_pages cp
SET related_count = sub.n
FROM (
    SELECT ce.slug,
           COUNT(*) FILTER (
               WHERE inner_sub.distance <= {RELATED_DISTANCE_THRESHOLD}
           ) AS n
    FROM collection_embeddings ce
    CROSS JOIN LATERAL (
        SELECT emb.embedding <-> ce.embedding AS distance
        FROM dataset_embeddings emb
        JOIN embedding_map m ON m.rowid = emb.rowid
        JOIN datasets d ON d.id = m.dataset_id
        WHERE d.resource_count > 0
        ORDER BY emb.embedding <-> ce.embedding
        LIMIT 500
    ) inner_sub
    GROUP BY ce.slug
) sub
WHERE cp.slug = sub.slug
"""

_TUNE = """
    SET work_mem = '64MB';
    SET synchronous_commit = off;
    SET hnsw.ef_search = 500
"""


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def build_semantic_related(db) -> int:
    """Build semantic related datasets via lateral KNN join."""
    print(f"  {_ts()} Semantic: running lateral join…", file=sys.stderr)
    t0 = time.monotonic()
    with db.conn.cursor() as cur:
        cur.execute(_SEMANTIC_LATERAL)
        inserted = cur.rowcount
    elapsed = time.monotonic() - t0
    print(f"  {_ts()} Semantic: {inserted:,} rows in {elapsed:.1f}s", file=sys.stderr)
    return inserted


def build_collection_related(db) -> tuple[int, int]:
    """Build collection related datasets and update related_count."""
    print(f"  {_ts()} Collections: inserting related datasets…", file=sys.stderr)
    t0 = time.monotonic()
    with db.conn.cursor() as cur:
        cur.execute(_COLLECTION_RELATED_LATERAL)
        rel_inserted = cur.rowcount
    elapsed = time.monotonic() - t0
    print(f"  {_ts()} Collections: {rel_inserted:,} related rows in {elapsed:.1f}s", file=sys.stderr)

    print(f"  {_ts()} Collections: updating related_count…", file=sys.stderr)
    t0 = time.monotonic()
    with db.conn.cursor() as cur:
        cur.execute(_COLLECTION_COUNT_UPDATE)
        updated = cur.rowcount
    elapsed = time.monotonic() - t0
    print(f"  {_ts()} Collections: {updated:,} counts updated in {elapsed:.1f}s", file=sys.stderr)

    return rel_inserted, updated


def main() -> None:
    print("Opening db…", file=sys.stderr)
    db = connect(DATABASE_URL)
    try:
        db.exec(_TUNE)
        print("Truncating baked tables…", file=sys.stderr)
        db.exec(_TRUNCATE)
        db.exec(_RESET_RELATED_COUNT)

        print("Building semantic related datasets…", file=sys.stderr)
        sem_rows = build_semantic_related(db)

        print("Building collection related datasets…", file=sys.stderr)
        crd_rows, _n_cols = build_collection_related(db)

        total = sem_rows + crd_rows
        print(f"\nDone — {total:,} total rows baked.", file=sys.stderr)
    finally:
        db.close()


if __name__ == "__main__":
    main()

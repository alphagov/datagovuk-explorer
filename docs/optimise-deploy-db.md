# Optimise deploy DB: bake related datasets

## The problem

Every dataset page view runs 3 queries to compute related datasets:

1. **EMBEDDING_LITERAL** — fetch the dataset's 768-dim vector from
   `dataset_embeddings` via `embedding_map`
2. **RELATED_BY_FTS** — full-text search "more like this" against the
   `fts` tsvector column, with series exclusion (top 20 by `ts_rank`)
3. **SEMANTIC_RELATED** — pgvector KNN against `dataset_embeddings`
   using the HNSW index, with series exclusion (top 20 by distance)

Every collection detail page runs 2:

1. **COLLECTION_EMBEDDING** — fetch the collection's vector from
   `collection_embeddings`
2. **COLLECTION_RELATED_DATASETS** — KNN against `dataset_embeddings`,
   filtered to datasets with resources (top 12 by distance)

The collections list page runs a **lateral nearest-neighbour search
per row**: for each collection on the page, find the 500 nearest
datasets by embedding distance and count how many fall within distance
0.77. Sorting by "related" requires computing
this for every collection that passes the filter.

All inputs are static between pipeline runs — the same dataset page
always produces the same related datasets until the next rebuild.

The embedding tables are large:

| Table | Total | Data | Indexes (HNSW) |
|---|---|---|---|
| `dataset_embeddings` | 372 MB | 2.4 MB | 369 MB |
| `embedding_map` | 7.5 MB | 3.7 MB | 3.8 MB |
| `collection_embeddings` | 416 KB | 8 KB | 408 KB |

**~380 MB** on disk, almost all HNSW indexes. The indexes aren't in
the dump itself (they're rebuilt during `pg_restore`), but the rebuild
is the slowest, most memory-hungry part of a restore — and at runtime
the indexes sit in shared buffers. The queries they serve are
recomputed identically on every page view.

## The idea

Pre-compute ("bake") **vector-based** related-dataset results into
simple lookup tables at build time. At request time, serve a trivial
indexed lookup instead of running embedding queries.

FTS related datasets stay live — each GIN lookup is fast at request
time, but baking them is impractical (see "Why FTS is not baked"
below).

- **Locally**: keep everything — embedding tables, HNSW indexes, the
  full pipeline. Rebuild baked tables whenever needed, experiment with
  thresholds or distance metrics freely.
- **Production**: only the baked tables ship. Exclude the embedding
  tables from the deploy dump, saving ~380 MB per dump/restore cycle
  and reducing the Railway Postgres memory footprint.

## New tables

### `related_datasets`

Pre-computed related datasets for the dataset detail page. Holds
semantic (vector) results only — FTS stays live.

```
related_datasets
  dataset_id   text     FK → datasets.id
  related_id   text     FK → datasets.id
  source       text     'semantic' (table supports 'fts' if needed later)
  rank         integer  position 1–20
  score        real     distance (semantic)
```

Index on `(dataset_id, source, rank)`.

~920k rows (46k datasets × 20 results). Each row is two text IDs, a
short string, a small int, and a float — a few MB total.

The request-time query joins through `datasets` to get the display
columns (`title`, `org_slug`, `org_display_name`, `metadata_modified`)
the templates need:

```sql
SELECT d.id, d.title, d.org_slug, d.org_display_name,
       d.theme_primary, d.metadata_modified,
       r.score AS distance
FROM related_datasets r
JOIN datasets d ON d.id = r.related_id
WHERE r.dataset_id = %s AND r.source = 'semantic'
ORDER BY r.rank
```

### `collection_related_datasets`

Pre-computed related datasets for the collection detail page.

```
collection_related_datasets
  slug         text     FK → collection_pages.slug
  dataset_id   text     FK → datasets.id
  rank         integer  position 1–12
  distance     real     L2 distance
```

Index on `(slug, rank)`.

~few hundred rows (small number of collections × 12 results each).

### `related_count` column on `collection_pages`

The collections list page currently runs a lateral KNN per row to
count datasets within the distance threshold. Replace with a
pre-computed integer column:

```
ALTER TABLE collection_pages ADD COLUMN related_count integer;
```

The lateral join in `_OVER_THRESHOLD_JOIN` and the
`collection_embeddings` join in the list query both go away. The sort
expression `COALESCE(related.count, 0)` becomes
`COALESCE(c.related_count, 0)`.

## Build step

`scripts/build_related.py` runs after `build-embeddings`. Three
lateral-join SQL statements do all the work in ~42 seconds:

1. **Truncate** the baked tables and reset `related_count`
2. **Dataset semantic related** — one `INSERT … SELECT` with a
   `CROSS JOIN LATERAL` KNN over the HNSW index per dataset embedding,
   inserting into `related_datasets` with `source = 'semantic'`
3. **Collection related datasets** — one lateral KNN `INSERT … SELECT`
   per collection embedding, into `collection_related_datasets`
4. **Collection related count** — one `UPDATE … FROM` with a lateral
   top-500 KNN and `COUNT(*) FILTER` for the distance threshold

`ROW_NUMBER() OVER (PARTITION BY …)` is computed outside each lateral
subquery so the HNSW ordered-scan + LIMIT path inside is unambiguous.

Justfile recipe:

```
build-related:
    uv run --env-file .env python -m scripts.build_related
```

The full build pipeline becomes:
`build-db` → `build-embeddings` → `build-related` → `ingest-reviews`
→ `ingest-suggestions` → `ingest-collections`

Update the Quickstart section and commands table in `readme.md` to
include `build-related` in the pipeline order.

## Query layer changes

### `explorer/queries/datasets.py`

`RELATED_BY_FTS` stays — still used live at request time (unchanged).

### `explorer/queries/embeddings.py`

`EMBEDDING_LITERAL` and `SEMANTIC_RELATED` stay (used at build time).
New request-time query:

```python
BAKED_SEMANTIC_RELATED = Query(
    """SELECT d.id, d.title, d.org_slug, d.org_display_name,
              d.theme_primary, d.metadata_modified, r.score AS distance
       FROM related_datasets r
       JOIN datasets d ON d.id = r.related_id
       WHERE r.dataset_id = %s AND r.source = 'semantic'
       ORDER BY r.rank""",
)
```

### `explorer/queries/collections.py`

`COLLECTION_EMBEDDING` and `COLLECTION_RELATED_DATASETS` stay (used at
build time). New request-time queries:

```python
BAKED_COLLECTION_RELATED = Query(
    """SELECT d.id, d.title, d.org_slug, d.org_display_name,
              d.theme_primary, d.metadata_modified, r.distance
       FROM collection_related_datasets r
       JOIN datasets d ON d.id = r.dataset_id
       WHERE r.slug = %s
       ORDER BY r.rank""",
)
```

The `_OVER_THRESHOLD_JOIN` lateral subquery is removed. The
`collections_stmts` list query uses `c.related_count` directly:

```python
COLLECTIONS_SORT = {
    ...
    "related": "COALESCE(c.related_count, 0)",
}
```

## View changes

### `explorer/views/dataset.py`

FTS stays live (unchanged from the original):
```python
match_str = build_match_string(dataset.get("title"), dataset.get("tags"))
related = RELATED_BY_FTS.all(match_str, dataset["id"], dataset["id"]) if match_str else []
```

Semantic switches to baked:
```python
semantic_related = BAKED_SEMANTIC_RELATED.all(dataset["id"])
```

### `explorer/views/collections.py`

Before:
```python
emb_row = COLLECTION_EMBEDDING.get(slug)
related_datasets = COLLECTION_RELATED_DATASETS.all(emb_row["embedding"]) if emb_row else []
```

After:
```python
related_datasets = BAKED_COLLECTION_RELATED.all(slug)
```

## Template changes

None. The baked queries alias columns to match what templates expect:
- `score AS distance` for semantic results (template uses `r.distance`
  and the `1.2 - r.distance` formula)
- `distance` for collection results (same formula + threshold styling)

FTS templates are unchanged — `RELATED_BY_FTS` still returns the same
columns.

The `distance_threshold` context variable stays — it's still used
by the collection detail template for red-flagging weak matches.

## Deploy changes

### `dump-db`

Add `--exclude-table-data` flags for the embedding tables. The table
definitions stay in the dump (migrations create them), but the data
and indexes don't ship:

```
pg_dump "$DATABASE_URL" \
  --no-owner --no-privileges --format=custom \
  --exclude-table-data=dataset_embeddings \
  --exclude-table-data=embedding_map \
  --exclude-table-data=collection_embeddings \
  --file="$dump_file"
```

This keeps the schema intact (migrations expect the tables to exist)
while dropping the vector row data from the dump and — crucially —
skipping the HNSW index rebuild during restore.

### `restore-db`

Remove `dataset_embeddings` from the autovacuum disable/enable and
VACUUM ANALYZE steps — the table will be empty in production.

### Local workflow

`dump-db` gets a variant or a flag for local backups that includes
everything. Or simply: the default `dump-db` is the deploy dump
(excludes embeddings), and a separate `dump-db-full` includes them.

## Migration

A single migration that:

1. Creates `related_datasets` with its index
2. Creates `collection_related_datasets` with its index
3. Adds `related_count` column to `collection_pages`

## Implementation status

Everything below is implemented and staged (not yet committed):

- Migration `0005_baked_related.py` — creates `related_datasets`,
  `collection_related_datasets`, adds `related_count` to
  `collection_pages`
- Models in `explorer/models.py`
- Baked queries in `explorer/queries/embeddings.py`,
  `explorer/queries/collections.py`
- Views: semantic switched to baked in `explorer/views/dataset.py`;
  FTS stays live (unchanged). Collections switched to baked in
  `explorer/views/collections.py`
- `justfile` — `build-related`, `dump-db` (excludes embeddings),
  `dump-db-full` (includes everything)
- `scripts/build_related.py` — lateral-join build script (~42s full
  run for semantic + collections)

**Not yet done:**
- Update `readme.md` quickstart and commands table to include
  `build-related` in the pipeline order

## Why FTS is not baked

### The bottleneck

Each FTS query matches **~14,700 datasets** on average (the OR-based
match strings are broad — ~25% of all datasets match). The GIN index
finds matches fast (2.5ms), but Postgres must heap-scan all 14,700 to
compute `ts_rank` before sorting and taking the top 20. That costs
~150ms per dataset.

EXPLAIN ANALYZE on 10 datasets (representative):

```
Bitmap Heap Scan on datasets d
  actual time=5.511..145.931 rows=12,687 loops=10
  Recheck Cond: (fts @@ websearch_to_tsquery(...))

  ->  Bitmap Index Scan on idx_datasets_fts
        actual time=2.450 rows=14,706 loops=10
```

The series exclusion is negligible (0.009ms). The cost is purely the
number of FTS matches being scored.

### Why the lateral join didn't help

The lateral join eliminated Python round-trips but the per-row cost
(~150ms) is the GIN heap scan + `ts_rank` computation, not the
round-trip. Both approaches run at ~5 datasets/second:

- **Python loop**: 47k round-trips × ~200ms = ~2.6 hours
- **Lateral join**: 1 statement, still 47k GIN scans × ~150ms = ~2 hours

The semantic pass was different — HNSW returns top-k in ~5ms per
dataset, so eliminating round-trips gave a 100× speedup.

### The pragmatic choice

FTS at request time is fast (~150ms per page view). Baking it would
save that 150ms but costs 2+ hours of build time. Not worth it — the
embedding tables (the deploy size/memory problem) are already handled
by baking semantic results only.

## Summary of savings

| | Current deploy | After baking |
|---|---|---|
| Dump size | ~2.4 MB of vector row data | A few MB for baked tables |
| Restore time | HNSW index rebuild is the bottleneck | Simple B-tree indexes |
| Runtime memory | HNSW index (~369 MB) in shared buffers | Negligible |
| Per-request cost (semantic) | 2 queries (embed lookup + KNN) | 1 indexed lookup |
| Per-request cost (FTS) | 1 query (unchanged) | 1 query (unchanged) |
| Collections list | Nearest-neighbour search per row | Column lookup |
| Build time | n/a | ~42 seconds |

# Performance comparison: before vs after optimisations

Two changes were made in early October 2026:

1. **Bake related datasets** (`735b876`, Oct 3) — pre-compute vector-based related datasets
   into lookup tables; exclude embedding tables from the deploy dump.
2. **Integer dataset PKs** (`33e641b`, Oct 4) — replace 36-char UUID text PK with a 4-byte
   int; keep `ckan_id` column for URL lookups.

## Method

- **Baseline**: Sep 30 dump (`explorer-2026-09-30.dump`) restored into a fresh
  `datagovuk_explorer_bench` database.
- **Current**: live `datagovuk_explorer` database (Oct 4 state).
- Query timings: `EXPLAIN (ANALYZE, BUFFERS)` via `psql`. Single runs on a warm cache.

---

## Storage

| | Baseline (Sep 30) | Current (Oct 4) | Change |
|---|---|---|---|
| **Deploy dump size** | 291 MB | 153 MB | **−47%** |
| **DB total size** | 1322 MB | 1778 MB | +456 MB (see note) |

> The current DB is larger than baseline because it includes `related_datasets` (194 MB),
> a larger `datasets` table due to int PK + `ckan_id` index, and growth in `links`,
> `suggestions` and `metadata_values` from continued pipeline runs. The deploy dump
> comparison is the meaningful number: it excludes embedding data in both cases (the
> pre-bake `dump-db` excluded the same tables; confirmed by the 291 MB size).

### Key tables

| Table | Baseline | Current | Notes |
|---|---|---|---|
| `dataset_embeddings` | 372 MB | 372 MB | Present locally; **excluded from deploy dump** |
| `embedding_map` | 7.5 MB | 4.1 MB | Shrunk (int FK smaller than UUID text) |
| `related_datasets` | — | 194 MB | New baked table (ships in deploy dump) |
| `collection_related_datasets` | — | 0.7 MB | New baked table |
| `datasets` | 131 MB | 260 MB | Doubled: int PK + ckan_id index added |
| `dataset_json` | 211 MB | 204 MB | Slight shrink (int FK column) |

---

## Query performance

### Q1: Dataset detail — semantic related datasets

| | Baseline | Current |
|---|---|---|
| **Queries** | 2: `EMBEDDING_LITERAL` + `SEMANTIC_RELATED` | 1: `BAKED_SEMANTIC_RELATED` |
| **Plan** | Index scan (embedding_map) → HNSW KNN scan + series exclusion subplan | Bitmap index scan (related_datasets) → PK lookup (datasets) |
| **Execution time** | 0.8 ms + 4.3 ms = **5.1 ms** | **3.3 ms** |

The HNSW KNN (4.3 ms) is replaced by a bitmap index scan on the pre-computed table.
The baked query also eliminates the two-step round-trip (fetch embedding, then query).

### Q2: Collections list — sort by "related count"

| | Baseline | Current |
|---|---|---|
| **Plan** | Seq scan (collection_pages + embeddings) → lateral KNN per row (83 × HNSW scan) | Seq scan (collection_pages) → in-memory sort |
| **Execution time** | **130 ms** | **1.7 ms** |
| **Speedup** | — | **76×** |

The lateral join ran an HNSW scan for every collection on the page (83 rows × ~1.6 ms each).
The baked `related_count` column reduces this to a single table scan.

### Q3: Collection detail — related datasets

| | Baseline | Current |
|---|---|---|
| **Queries** | 2: `COLLECTION_EMBEDDING` + `COLLECTION_RELATED_DATASETS` | 1: `BAKED_COLLECTION_RELATED` |
| **Plan** | Seq scan (collection_embeddings) → HNSW KNN on dataset_embeddings | Bitmap index scan (collection_related_datasets) → PK lookup (datasets) |
| **Execution time** | 1.4 ms + 2.2 ms = **3.6 ms** | **2.9 ms** |

Modest improvement — the HNSW index was already fast for 12 results. Main benefit is
eliminating the two-query round-trip and removing the dependency on `collection_embeddings`
at request time.

---

## Summary

| | Baseline | Current | Improvement |
|---|---|---|---|
| Deploy dump | 291 MB | 153 MB | **−138 MB (−47%)** |
| Dataset detail (semantic) | 5.1 ms (2 queries) | 3.3 ms (1 query) | −36%, −1 query |
| Collections list sort | 130 ms | 1.7 ms | **−76×** |
| Collection detail | 3.6 ms (2 queries) | 2.9 ms (1 query) | −20%, −1 query |

The collections list sort is the standout win: a lateral KNN per row scaled linearly with
collection count; the baked column makes it constant. The deploy dump reduction (−47%)
comes entirely from excluding embedding table data, which was the primary motivation for
the bake.

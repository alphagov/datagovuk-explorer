# Migrate dataset PK from text UUID to integer

## Context

The `datasets` table uses the 36-char CKAN UUID as its TEXT primary key.
That UUID is stored in 12 FK columns across 10 other tables, plus their
indexes. Switching to a 4-byte integer PK saves ~250–300 MB (~15–20% of
the DB), and makes every dataset join faster (smaller keys = better cache
utilisation + faster B-tree lookups).

The DB is rebuilt from scratch (`just fresh-db`), so no live data migration
is needed — we change the schema and the build scripts, then rebuild.

## Key decisions

- **Keep the CKAN UUID in URLs** (`/dataset/{org}/{uuid}`). Integer IDs
  are unstable across rebuilds; UUIDs are the canonical external identifier.
  A unique indexed `ckan_id` column provides the URL-to-row lookup.
- **AutoField (4-byte int)** as the new PK — 59k rows, no need for BigAutoField.
- **`dataset_json.id`** column renamed to `dataset_json.dataset_id` for
  clarity (it's no longer the CKAN UUID, it's an int FK).

## Changes by area

### 1. Model (`explorer/models.py`)

**Dataset** — remove `id = TextField(primary_key=True)`, add `ckan_id = TextField(unique=True)`.
Django auto-creates an `id` AutoField PK. Update `idx_datasets_reviews_cover`
to use `ckan_id` instead of `id`. Update `__str__` fallback from `self.id`
to `self.ckan_id`.

**FK models** (TemporalPeriod, Link, EmbeddingMap, Review, Suggestion,
CollectionRelatedDataset, DatasetApi, DatasetContentHash, DatasetJson) —
the ForeignKey/OneToOneField declarations already point at `Dataset`;
Django handles the type change automatically. **DatasetJson**: change
`db_column="id"` to `db_column="dataset_id"`.

**Plain TextField references** — `SeriesDataset.dataset_id` and
`RelatedDataset.dataset_id`: change from `TextField()` to `IntegerField()`.

### 2. Migration (`explorer/migrations/0007_*.py`)

Django's auto-generated migration will likely struggle with the PK type
change + cascading FK changes. Write a custom migration with `RunSQL`:

1. Drop all FK constraints and indexes referencing `datasets.id`
2. Rename `datasets.id` → `datasets.ckan_id`
3. Add `datasets.id SERIAL PRIMARY KEY`
4. Add unique index on `datasets.ckan_id`
5. For each child table: add temp int column, populate via
   `UPDATE child SET new_col = d.id FROM datasets d WHERE d.ckan_id = child.dataset_id`,
   drop old text column, rename new column
6. Recreate FK constraints and indexes
7. Handle `dataset_json.id` → `dataset_json.dataset_id` rename

Since the DB is rebuilt from scratch, the migration just needs to produce
the correct final schema. A simpler alternative: use `SeparateDatabaseAndState`
to tell Django "the schema now looks like this" and let `fresh-db` (which
drops + creates + migrates) handle the actual DDL. The migration only needs
to work on an empty DB.

### 3. Build pipeline (`scripts/build_db.py`)

**INSERT_DATASET_SQL**: change `id` to `ckan_id` in the column list;
remove it from `ON CONFLICT` (use `ckan_id` instead); let `id` auto-generate.

**After dataset insert, build a UUID→int mapping:**
```python
id_map = {r["ckan_id"]: r["id"] for r in db.prepare("SELECT id, ckan_id FROM datasets").all()}
```

**Child table inserts** (INSERT_PERIOD_SQL, INSERT_JSON_SQL, INSERT_LINK_SQL):
replace `ds.get("id")` with `id_map[ds.get("id")]` for the FK value.

**INSERT_JSON_SQL**: column changes from `id` to `dataset_id`.

**_populate_fts_tx**: `WHERE id = ?` stays (it's the int PK now), but the
parameter changes from the UUID to the int. The `fts_rows` dict needs to
carry the int ID: change `_fts_row()` to accept and store the int ID.

**_write_views_tx**: `WHERE id = ?` → `WHERE ckan_id = ?` (the CSV maps
UUIDs to view counts; the lookup must be by UUID, not int).

**INSERT_DATASET_API_SQL / INSERT_DATASET_CONTENT_HASH_SQL**: these are
pure SQL joining `datasets` to `links` on `l.dataset_id = datasets.id` —
they work unchanged since both sides are now integers.

**_meta_counts**: uses `ds.get("id")` for dedup only (a set) — no DB
interaction, no change needed.

### 4. Other pipeline scripts

**`scripts/build_series.py`**: writes `series_datasets(series_id, dataset_id)`.
Currently `dataset_id` is the UUID text. Must resolve to int via the mapping.
Either pass the mapping in, or query it at the start of the script.

**`scripts/build_related.py`**: writes `related_datasets(dataset_id, rank, related_id)`.
Both `dataset_id` and `related_id` are text UUIDs. The script runs SQL
that joins `datasets` — the joins already use `d.id` which becomes the int.
Check whether the INSERT uses the UUID directly or derives from a query result.

**`scripts/build_embeddings.py`**: writes `embedding_map(rowid, dataset_id)`.
Same pattern — resolve UUID to int.

**`scripts/llm/ingest_reviews.py` and `ingest_suggestions.py`**: both do
`COPY ... (dataset_id, ...)` with the UUID from JSON files on disk. Must
resolve UUID → int before COPY. Pattern:
```python
id_map = {r["ckan_id"]: r["id"] for r in db.prepare("SELECT id, ckan_id FROM datasets").all()}
```
Then replace `r["dataset_id"]` with `id_map[r["dataset_id"]]` in the COPY rows.

The existence check `SELECT id FROM datasets WHERE id = ANY(?)` →
`SELECT ckan_id FROM datasets WHERE ckan_id = ANY(?)`, and filter by `ckan_id in existing`.

**`scripts/llm/common.py`**: `record_base()` sets `dataset_id: row["id"]`.
`row["id"]` comes from a query on `datasets` — after migration this would
be the int. But the LLM output files use the UUID in filenames
(`record['dataset_id'][:8]`). Need to keep the UUID in the record:
use `row["ckan_id"]` instead.

### 5. Query layer (`explorer/queries/`)

**Joins are mostly unchanged**: `d.id = x.dataset_id` still works because
both sides are now integers.

**SELECTs for template URLs**: everywhere that `d.id` is selected and
used in templates to build `/dataset/{org}/{id}` links, change to
`d.ckan_id`. This affects ~15 query locations across:
- `datasets.py` — list queries selecting `d.id` for links
- `reviews.py` — `r.dataset_id` in SELECT (now an int, need `d.ckan_id`)
- `suggestions.py` — same pattern
- `links.py` — `l.dataset_id` in SELECT
- `link_errors.py` — `l.dataset_id AS package_id`
- `series.py` — `sd.dataset_id` in SELECT
- `search.py` — `d.id` in SELECT
- `collections.py` — `r.dataset_id` / `m.dataset_id` in SELECT
- `reports.py` — `d.id` and `l.dataset_id` in SELECT
- `harvesters.py` — `d.id` in SELECT
- `organisations.py` — join uses `d.id = r.dataset_id` (unchanged)

**WHERE clauses with UUID parameters** (detail page lookups):
- `datasets.py` DATASET_JSON: `WHERE id = %s` → `WHERE dataset_id = %s`
  (also the column was renamed from `id` to `dataset_id`)
- `datasets.py` DATASET_TEMPORAL_PERIODS: `WHERE dataset_id = %s` — the
  parameter changes from UUID to int (caller provides int after lookup)
- `reviews.py` `_REVIEW_FOR`: `WHERE dataset_id = %s` — int parameter
- `suggestions.py` `_SUGGESTION_FOR`: `WHERE dataset_id = %s` — int parameter
- `embeddings.py`: `WHERE dataset_id = %s` / `m.dataset_id = %s` — int
- `series.py` DATASET_SERIES: `WHERE dataset_id = %s` — int

### 6. Views (`explorer/views/`)

**`dataset.py`** — the main entry point where a UUID arrives from the URL.
Current flow: `dataset_id` (UUID string) → passed directly to all queries.
New flow:
1. Look up the dataset row: query `datasets` WHERE `ckan_id = %s` to get
   the integer `id` (can be combined with the JSON fetch)
2. Pass the integer `id` to all subsequent queries (reviews, suggestions,
   temporal periods, series, related)
3. The CKAN JSON blob (`dataset["id"]`) still contains the UUID for display

No other views need changes — they don't receive dataset IDs from URLs.

### 7. Templates

Every template that builds a dataset URL currently uses `{{ ds.id }}` or
`{{ ds.dataset_id }}` (the UUID from the SELECT). After migration, these
columns are integers. Templates must use the CKAN UUID for URLs.

Two approaches:
- **A)** Change queries to `SELECT d.ckan_id` and templates to `{{ ds.ckan_id }}`
- **B)** Alias in SQL: `SELECT d.ckan_id AS ckan_id` and update templates

Approach A is clearer. Templates to update (~15 locations):
- `datasets.html`: `ds.id` → `ds.ckan_id`
- `dataset.html`: `dataset.id` display stays (it's from the JSON blob, still a UUID)
- `search.html`, `search_datasets.html`: `d.id` → `d.ckan_id`
- `links.html`: `l.dataset_id` → `l.ckan_id` (need to SELECT it)
- `links_errors.html`: `e.package_id` → `e.ckan_id`
- `report.html`: `row.id` / `row.dataset_id` → `row.ckan_id`
- `reviews.html`: `r.dataset_id` → `r.ckan_id`
- `suggestions.html`: `s.dataset_id` → `s.ckan_id`
- `series_detail.html`: `ds.dataset_id` → `ds.ckan_id`
- `harvester.html`: `ds.id` → `ds.ckan_id`
- `collection_detail.html`: `r.id` → `r.ckan_id`

### 8. URL config (`config/urls.py`)

No change — keep `<str:dataset_id>` since the UUID is still in the URL.

### 9. Tests

**`conftest.py`**: fixtures use short strings like `"d01"`, `"d02"` as
dataset IDs. These become `ckan_id` values. The integer PK auto-generates.
Update fixture inserts to use `ckan_id` column.

**`tests/test_build_db.py`**: hardcoded UUIDs for views tests, short IDs
for build tests. Update INSERT SQL and assertions.

**`tests/test_build_series.py`**, **`test_build_series_db.py`**: short IDs
like `"a1"`, `"bs-1"`. Same pattern.

**`tests/test_llm_*.py`**: UUID strings in records. Update to resolve
through the mapping.

**`explorer/tests/test_integration_queries.py`**: references `"d01"` for
lookups. Update to use `ckan_id`.

### 10. `scripts/llm/review.py` and `suggest.py`

The `--dataset <id>` CLI option passes the UUID for a single-dataset run.
The query `SELECT ... FROM datasets WHERE id = ?` → `WHERE ckan_id = ?`.

## Implementation order

1. Model + migration (get the schema right)
2. `build_db.py` (the core pipeline — biggest single file)
3. Other pipeline scripts (build_series, build_related, build_embeddings)
4. LLM ingest scripts (ingest_reviews, ingest_suggestions)
5. LLM run scripts (review.py, suggest.py, common.py)
6. Query layer (all `explorer/queries/*.py` modules)
7. Views (dataset.py)
8. Templates (~15 files)
9. Tests (conftest.py + all test files)
10. Verify: `just fresh-db && just ingest-reviews && just ingest-suggestions && just test && just dev`

## Verification

1. `just fresh-db` — schema creates cleanly, build completes, row counts match
2. `just ingest-reviews && just ingest-suggestions` — LLM data loads
3. `just lint` — no ruff errors
4. `just test` — all tests pass
5. `just dev` — browse the app:
   - Dataset list page (links work, point to UUID URLs)
   - Dataset detail page (loads correctly, review/suggestion/series show)
   - Search works
   - Reports load
   - Reviews/suggestions list pages
6. Check DB sizes: `SELECT relname, pg_size_pretty(pg_total_relation_size(c.oid)) ...`
   to confirm the size reduction

# Refactor: split build_db.py into core ingestion + derived table scripts

> **Rename:** `build_db.py` → `ingest_ckan.py` as part of this refactor.
> The file becomes purely CKAN ingestion; the old name no longer fits.

## Goal

`scripts/build_db.py` (1375 lines) does two distinct jobs:

1. **Mirror CKAN data** into core tables — orgs, harvest sources, datasets,
   links, temporal periods, raw JSON
2. **Derive analysis tables** — FTS, metadata field counts, dataset_api,
   dataset_content_hash, dataset_years, plus view counts from GA/SC CSVs

These evolve independently. The derived tables get tweaked and experimented
with; the core ingestion rarely changes. Splitting them apart makes each
job findable, readable, and independently runnable — you can rebuild FTS
or duplicate detection without a full 50k-dataset re-ingestion.

## Architecture after the refactor

```
ingest_ckan (core CKAN tables)
  ├── build_fts                   (reads datasets)
  ├── build_metadata              (reads dataset_json)
  ├── build_dataset_api           (reads datasets + links)
  ├── build_dataset_content_hash  (reads datasets + links)
  ├── build_dataset_years         (reads temporal_periods)
  └── ingest_views                (reads GA/SC CSVs, writes to datasets)
```

Everything depends on `ingest_ckan` having run. Nothing depends on each other.
After the core load, the derived scripts can run in any order. Every derived
script does TRUNCATE + INSERT (or UPDATE for views), so they are all
idempotent — re-running is always safe.

The justfile is the orchestrator. `build-db` chains the steps in sequence.
Each step also has its own `just` recipe for standalone use.

## File plan

| New file | Lines (approx) | Source | What it does |
|---|---|---|---|
| `build_fts.py` | ~60 | Reads `datasets` table | Populate tags + fts tsvector columns |
| `build_metadata.py` | ~80 | Reads `dataset_json` table | Field/value usage counts → metadata_keys/metadata_values |
| `build_dataset_api.py` | ~60 | Reads `datasets` + `links` | API detection snapshot → dataset_api |
| `build_dataset_content_hash.py` | ~50 | Reads `datasets` + `links` | Duplicate detection hash → dataset_content_hash |
| `build_dataset_years.py` | ~40 | Reads `temporal_periods` | Year expansion → dataset_years |
| `ingest_views.py` | ~60 | Reads GA/SC CSVs in `data/` | View counts → datasets.views |

`build_db.py` is renamed to `ingest_ckan.py` and keeps: transform functions,
core ingestion, `_BuildState`, file reading/parsing, org/harvest-source/dataset
loading. It drops to ~800 lines. The transform functions (`normalise_format`,
`extract_host`, `temporal_*`) stay — they are ingestion-internal and only
tested through `tests/test_ingest_ckan.py` (renamed from
`tests/test_build_db.py`). `field_value_str` moves to `build_metadata.py`
(it's only used by the metadata counters).

## Steps

Work through these in order. Run `just lint` and `just test` after each
step to confirm nothing breaks. Each step should be a single commit.

### 1. Rename `build_db.py` → `ingest_ckan.py`

Do the rename first so all subsequent steps work against the new name.

1. `git mv scripts/build_db.py scripts/ingest_ckan.py`
2. `git mv tests/test_build_db.py tests/test_ingest_ckan.py`
3. In `tests/test_ingest_ckan.py`: update `import scripts.build_db as bd`
   → `import scripts.ingest_ckan as bd` (keep the `bd` alias to minimise
   churn in the test file)
4. In the justfile: update `build-db` and `fresh-db` recipes from
   `python -m scripts.build_db main` → `python -m scripts.ingest_ckan main`
   (keep the `main` subcommand argument — other subcommands still exist
   at this point; step 8 removes them)
5. In `readme.md`: update any references to `build_db.py`
6. In `CLAUDE.md` / `agents.md`: update any references if present
7. Run `just lint` and `just test` to confirm.

### 2. Extract `build_dataset_api.py`

This is the simplest extraction — pure SQL, no Python logic, already a
working subcommand.

1. Create `scripts/build_dataset_api.py`:
   - Move `_BUILD_API_SIGNAL`, `_BUILD_API_TYPE_CASE`, `_BUILD_MAP_LAYER_TYPES`,
     `INSERT_DATASET_API_SQL`, and `_populate_dataset_api` from `ingest_ckan.py`
   - Add a `main()` that connects, calls `TRUNCATE TABLE dataset_api`,
     calls `_populate_dataset_api`, prints the count + category breakdown
     (copy from the existing `dataset_api` subcommand), and closes
   - Use `typer` CLI entry point, same pattern as the existing subcommand
   - Import `connect` and `database_url` from `scripts.db`
2. In `ingest_ckan.py`:
   - Remove the moved constants, SQL, and function
   - Remove the Phase 10 call from `build()` entirely (the justfile
     orchestrates this step now)
   - Remove the `dataset_api` subcommand
3. Update the justfile `build-dataset-api` recipe to point at the new script:
   `uv run --env-file .env python -m scripts.build_dataset_api`

### 3. Extract `build_dataset_content_hash.py`

Same pattern as step 2.

1. Create `scripts/build_dataset_content_hash.py`:
   - Move `INSERT_DATASET_CONTENT_HASH_SQL` and `_populate_dataset_content_hash`
   - Add a `main()` that connects, truncates, populates, prints count +
     duplicate hash groups (copy from existing subcommand), closes
2. In `ingest_ckan.py`:
   - Remove the moved code
   - Remove the Phase 11 call from `build()` entirely
   - Remove the `dataset_content_hash` subcommand
3. Update justfile `build-dataset-content-hash` recipe.

### 4. Extract `build_dataset_years.py`

Same pattern as step 2.

1. Create `scripts/build_dataset_years.py`:
   - Move `INSERT_DATASET_YEARS_SQL` and `_populate_dataset_years`
   - Add a `main()` that connects, calls `_populate_dataset_years`
     (it already does its own TRUNCATE), prints count, closes
2. In `ingest_ckan.py`:
   - Remove the moved code
   - Remove the Phase 5 call from `build()` entirely
   - Remove the `dataset_years` subcommand
3. Update justfile `build-dataset-years` recipe.

### 5. Extract `ingest_views.py`

Views reads from CSVs, not from the database load — it's the most
naturally independent piece.

1. Create `scripts/ingest_views.py`:
   - Move `load_views_csv`, `_read_ga_csv`, `_read_search_console_csv`,
     `_write_views_tx`, `CONSENT_RATE_FLOOR`, and the three CSV path
     constants (`VIEWS_FILE`, `GA_PAGE_VIEWS_FILE`, `GA_GOOGLE_LANDING_FILE`)
   - Add a `main()` that connects, resets views to 0, loads CSVs, writes,
     prints count, closes (copy from the existing `views` subcommand)
2. In `ingest_ckan.py`:
   - Remove the moved code
   - Remove the Phase 8 call from `build()` entirely
   - Remove the `views` subcommand
   - `CONSENT_RATE_FLOOR` is duplicated in `ingest_collections.py` with a
     comment saying "kept in sync" — after extraction both scripts own their
     own copy; leave the sync comment pointing at both files
3. Update justfile `ingest-views` recipe to point at the new script.

### 6. Extract `build_fts.py`

Currently FTS accumulates `st.fts_rows` during the dataset load loop, then
writes them in Phase 7. To make it independently runnable, the new script
must read from the database instead.

1. Create `scripts/build_fts.py`:
   - Write a function that reads title and notes from the `datasets` table,
     and tag names from the raw JSON in `dataset_json` (the `datasets.tags`
     column is NULL until this script populates it — it can't read from
     itself)
   - Set `tags` (space-joined string) and compute the `fts` tsvector, same
     as the current `_populate_fts_tx`
   - The current version loops over pre-built dicts; the new version should
     do it in SQL or read rows from the DB and update in batches
   - Add a `main()` CLI entry point
2. In `ingest_ckan.py`:
   - Remove `_populate_fts_tx` and the `_fts_row` function
   - Remove `st.fts_rows` from `_BuildState`
   - Remove the `st.fts_rows.append()` call from `_process_batch`
   - Remove the Phase 7 call from `build()` entirely
3. Add a justfile `build-fts` recipe.

### 7. Extract `build_metadata.py`

Same decoupling as FTS — currently accumulates `st.field_counts` and
`st.value_counts` during the load, writes in Phase 9. The new script reads
from `dataset_json` instead.

1. Create `scripts/build_metadata.py`:
   - Write a function that reads the raw JSON from `dataset_json`, iterates
     over the top-level fields and extras (same logic as `_meta_counts`),
     builds the field/value counters, then writes them with the same INSERT
     logic as `_write_meta_tx`
   - Deduplicate by `dataset_id` (same guard as the current `seen_meta_ids`)
   - Add a `main()` CLI entry point
2. In `ingest_ckan.py`:
   - Remove `_meta_counts`, `_write_meta_tx`, `field_value_str`
   - Remove `st.field_counts`, `st.value_counts`, `st.seen_meta_ids` from
     `_BuildState`
   - Remove the `_meta_counts()` call from `_process_batch`
   - Remove the Phase 9 call from `build()` entirely
   - `field_value_str` is tested in `tests/test_ingest_ckan.py` — move those
     tests to a new `tests/test_build_metadata.py` and import from the new
     module
3. Add a justfile `build-metadata` recipe.

### 8. Update the justfile orchestration

After all extractions, update `build-db` and `fresh-db`:

```just
build-db: migrate
    uv run --env-file .env python -m scripts.ingest_ckan
    uv run --env-file .env python -m scripts.build_dataset_years
    uv run --env-file .env python -m scripts.build_fts
    uv run --env-file .env python -m scripts.ingest_views
    uv run --env-file .env python -m scripts.build_metadata
    uv run --env-file .env python -m scripts.build_dataset_api
    uv run --env-file .env python -m scripts.build_dataset_content_hash
    psql $DATABASE_URL -c "REFRESH MATERIALIZED VIEW mv_org_aggregates"
    uv run --env-file .env python -m scripts.build_harvester_stats
```

The order after `ingest_ckan` doesn't matter (no inter-dependencies), but
group logically: years and FTS first (they feed user-facing search/filter),
then views, then the analysis tables.

Remove the subcommands from `ingest_ckan.py` (`dataset_api`, `views`,
`dataset_content_hash`, `dataset_years`). The `main` subcommand becomes
the only entry point — simplify to just `app()` calling `build()` directly.

Update `TRUNCATE_SQL` in `ingest_ckan.py` to only truncate the core tables
it owns (`organisations`, `harvest_sources`, `datasets`, `dataset_json`,
`links`, `temporal_periods`, `embedding_map`, `dataset_embeddings`). Remove
the derived tables (`dataset_years`, `dataset_api`, `dataset_content_hash`,
`metadata_keys`, `metadata_values`) — each derived script handles its own
TRUNCATE.

Update the justfile recipes from `python -m scripts.ingest_ckan main` to
`python -m scripts.ingest_ckan` (no subcommand needed now).

### 9. Update the README

Update the quickstart and command table in `readme.md` to list the new
standalone recipes (`build-fts`, `build-metadata`) and note that each
derived table can be rebuilt independently.

## What stays in `ingest_ckan.py`

After all steps, `ingest_ckan.py` contains:

- Transform functions: `temporal_val`, `temporal_year`, `temporal_periods`,
  `_text_periods`, `_suggested_periods`, `_dedupe_periods`, `_stringify`,
  `extract_host`, `_whatwg_normalize`, `_idna_host`, `normalise_format`
  and their supporting regexes/constants (`field_value_str` moves to
  `build_metadata.py`)
- Core ingestion: `TRUNCATE_SQL`, all `INSERT_*_SQL` statements (datasets,
  links, periods, JSON), `_BuildState`, `_read_parse`, `_extras`,
  `_dataset_row`, `_dataset_period_rows`, `_link_rows`, `_process_batch`,
  `_load_orgs`, `_load_harvest_sources`, `_collect_files`,
  `_load_organisations_tx`, `_load_harvest_sources_tx`
- `build()` — core CKAN ingestion only; derived tables are separate scripts
  chained by the justfile
- `main()` — the single CLI entry point

Estimated: ~800 lines.

## Not in scope

- Changing `explorer/` — it reads from the database and is unaffected
- Changing the schema or migrations
- Extracting the transform functions — they are ingestion-internal, only
  called within `ingest_ckan.py`, and only tested through
  `tests/test_ingest_ckan.py`
- `check_links.py`, `build_series.py`, `build_embeddings.py` — separate concern

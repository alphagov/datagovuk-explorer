# Fetch Data Run Report — 2026-09-14

Full pipeline run: fetch organisations → fetch harvest sources → download datasets → build DB → ingest reviews.

## Summary

| Step | Result |
|---|---|
| fetch-organisations | 1,043 organisations |
| fetch-harvest-sources | 515 harvest sources |
| download-datasets | 67,527 datasets, 21 batches, 0 errors |
| build-db | 67,544 datasets, 304,408 resource links, 0 files skipped |
| ingest-reviews | 996 inserted, 30 skipped (dataset not in local DB) |

Note: dataset count differs slightly between download (67,527 files) and build (67,544). The build walks `downloads/` directly and may pick up files from a previous partial run that weren't overwritten.

## Issues encountered

### 1. `download-datasets` silently no-ops on a machine with existing data

**What happened:** Running `just download-datasets` (or `just download-datasets --continuous --per-org all`) on a machine that already has a populated `downloads/` directory exits immediately with "0 datasets saved across 0 batch(es)." No warning is printed. The script's `select_batch` function skips any org that already has files in `downloads/<org-name>/`, so without `--force` the entire run is a no-op.

**Impact:** A user following the README "full run" steps to refresh data would get silently stale data.

**Suggestion:** Print a prominent warning when `--continuous` exits with 0 datasets saved and `--force` was not passed, e.g.:
```
Warning: all organisations already have saved data. Use --force to re-fetch.
```

### 2. `just build-db` broken — missing `main` subcommand

**What happened:** `build-db` failed with `No such option: --skip-embeddings` (exit code 2). The `scripts/build_db.py` CLI was refactored to use subcommands (`main`, `dataset-api`) but the justfile recipe was not updated to match. The recipe passed args directly to the top-level command instead of forwarding them to the `main` subcommand.

**Fix applied:** Updated `justfile` line 78:
```diff
- uv run --env-file .env python -m scripts.build_db {{args}}
+ uv run --env-file .env python -m scripts.build_db main {{args}}
```

The `fresh-db` recipe also calls `build-db` and would have inherited the same breakage.

### 3. 172 unmatched views URLs

**What happened:** During `build-db`, 172 dataset view records could not be matched to a dataset (neither by clean URL nor date-redacted URL). These datasets have no views data.

**Suggestion:** Worth investigating whether these are genuinely deleted datasets or a matching heuristic gap. The views CSV may contain slugs that have been renamed on data.gov.uk.

### 4. 30 reviews skipped — datasets no longer in local DB

**What happened:** `ingest-reviews` skipped 30 of 1,026 review records because their `dataset_id` was not found in the freshly built `datasets` table. These datasets were previously reviewed by the LLM but have since been removed from data.gov.uk (or weren't present in this snapshot).

**Suggestion:** Log the skipped `dataset_id` values so it's easy to audit whether they were genuinely deleted from data.gov.uk or are a pipeline gap.

## Commands used

```bash
just fetch-organisations
just fetch-harvest-sources
just download-datasets --continuous --force --per-org all   # --force required to refresh
just build-db --skip-embeddings
just ingest-reviews
```

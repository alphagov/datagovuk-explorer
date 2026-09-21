# Fetch Data Run Report — 2026-09-18

Full pipeline run: fetch organisations → fetch harvest sources → download datasets → build DB → ingest reviews → embeddings.

## Final results (after cleanup)

| Step | Result | Time |
|---|---|---|
| fetch-organisations | 1,043 organisations | 31s |
| fetch-harvest-sources | 515 harvest sources | 5m 25s |
| download-datasets | 58,264 datasets, 21 batches, 0 errors | 13m 02s |
| build-db | 58,264 datasets, 232,849 resource links, 0 files skipped | 2m 56s |
| ingest-reviews | 918 inserted, 108 skipped (dataset not in local DB) | 1s |
| build-series | 3,996 series (680 template, 3,316 timeseries) | 4s |
| embed-only | 58,264 datasets embedded, HNSW index rebuilt | 9m 30s |
| dump-db | explorer-2026-09-18.dump | 27s |
| restore-db | Railway Postgres restored | 4m 27s |
| deploy | Code shipped, health: 200 | ~2m |

**Total wall-clock time: ~40 minutes** (fetch through deploy).

Dataset count (58,264) now matches data.gov.uk's search total.

## Issues encountered

### 1. `build-db` crash: UniqueViolation on `temporal_periods` (fixed)

**What happened:** The first `build-db` run crashed ~47s in at ~20,000 datasets:

```
UniqueViolation: duplicate key value violates unique constraint "temporal_periods_pkey"
DETAIL: Key (dataset_id, "position")=(bc9e2d89-583b-469e-bdf7-f3d68fbcd8ba, 0) already exists.
```

**Root cause:** Dataset `bc9e2d89-583b-469e-bdf7-f3d68fbcd8ba` ("CCTV Development on Western Irish Sea Nephrops Vessels") exists under two organisations:
- `centre-for-environment-fisheries-aquaculture-science`
- `marine-environmental-data-information-network`

The `INSERT_DATASET_SQL` has `ON CONFLICT (id) DO UPDATE SET ...` and handles this fine. But `INSERT_PERIOD_SQL` had no `ON CONFLICT` clause — the comment said "no dataset id repeats in the file set", which is no longer true. 11 datasets total appear under multiple orgs in the current download set.

**Fix applied:** Added `ON CONFLICT (dataset_id, position) DO UPDATE SET` to `INSERT_PERIOD_SQL` in `scripts/build_db.py`, matching the upsert pattern used by the dataset and JSON inserts. Updated the stale comment.

### 2. 9,672 stale dataset files inflating the build (fixed)

**What happened:** The initial build processed 67,936 files — ~9,700 more than the 58,264 downloaded this run. The `--force` flag in `download-datasets` overwrites existing files but never deletes files that CKAN no longer returns. Datasets removed from data.gov.uk (or moved between orgs) since the previous run were still sitting in `downloads/` and getting built.

**Fix applied:** Updated `scripts/download_datasets.py` — when `--force` is set, each org directory's `.json` files are now wiped before fetching, so only what CKAN returns survives. For this run, deleted the stale files by date (`! -newermt 2026-09-18`) and re-ran `build-db` + `ingest-reviews`.

### 3. 145 unmatched views URLs (improved from 172)

**What happened:** During `build-db`, 145 dataset view records could not be matched to a dataset (neither by clean URL nor date-redacted URL). Down from 172 in the first report — the cleaned dataset set is more accurate.

### 4. 108 reviews skipped — datasets no longer in local DB

**What happened:** `ingest-reviews` skipped 108 of 1,026 review records because their `dataset_id` was not found in the freshly built `datasets` table. Up from 28 before the stale-file cleanup — those 80 extra skips were datasets that had been removed from data.gov.uk but were still present as stale files in the previous build.

## Commands used

```bash
just fetch-organisations
just fetch-harvest-sources
just download-datasets --continuous --force --per-org all
just build-db --skip-embeddings                              # failed: UniqueViolation
# fixed INSERT_PERIOD_SQL in scripts/build_db.py (added ON CONFLICT)
just build-db --skip-embeddings                              # succeeded, but 67,936 files (stale)
# deleted 9,672 stale files: find downloads -name "*.json" ... ! -newermt "2026-09-18" -delete
# fixed download_datasets.py to wipe org dirs before re-fetching with --force
just build-db --skip-embeddings                              # 58,264 — matches data.gov.uk
just ingest-reviews
just build-series
just embed-only                                              # llama-server on :8080
just dump-db
just tunnel                                                  # in separate terminal
just restore-db db/backups/explorer-2026-09-18.dump <railway-url>
just deploy
just deploy-check                                            # health: 200
```

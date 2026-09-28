# Rename dataset_json.id → dataset_id

**Status: planned.**

## The problem

Every OneToOne-to-Dataset table uses `dataset_id` as its FK column name
(`dataset_api.dataset_id`, `dataset_content_hash.dataset_id`,
`collection_embeddings.slug`). `dataset_json` is the only one that uses
`id` — a leftover from the original 0001 migration. It reads like the
table's own surrogate key rather than a foreign key.

## What to change

### 1. Model (`explorer/models.py`)

Change `DatasetJson.dataset` from `db_column="id"` to
`db_column="dataset_id"`.

### 2. Migration

Add a migration with `RenameField` or `RunSQL`:

```sql
ALTER TABLE dataset_json RENAME COLUMN id TO dataset_id;
```

Since all environments rebuild from scratch, the column will simply be
created as `dataset_id` from the start in `0001_initial`. If an
in-place migration is ever needed, the ALTER is safe — it's a metadata
rename, no data rewrite.

### 3. Raw SQL (4 files, 5 references)

| File | Line | Current | After |
|---|---|---|---|
| `explorer/queries/datasets.py` | 252 | `dj.id = d.id` | `dj.dataset_id = d.id` |
| `explorer/queries/datasets.py` | 527 | `WHERE id = %s` | `WHERE dataset_id = %s` |
| `scripts/build_db.py` | 638 | `INSERT INTO dataset_json (id, json)` | `INSERT INTO dataset_json (dataset_id, json)` |
| `scripts/review_suggest.py` | 764 | `j.id = d.id` | `j.dataset_id = d.id` |

### 4. Tests

`conftest.py` line 415 already uses `dataset_id=row["id"]` via the
Django model (the ORM-level field name stays `dataset`), so no change
needed there. `tests/test_review_suggest.py` line 56 is a comment — no
code change.

## Verification

1. `makemigrations --check` — no drift
2. `just build-db` — populates without error
3. `just test` — all tests pass
4. Spot-check: `/datasets`, dataset detail page, metadata JSON view

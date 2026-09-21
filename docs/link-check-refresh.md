# Link check refresh — plan

## Problem

`link_check_results` has a FK to `links` with `ON DELETE CASCADE`. When `build_db`
runs a full rebuild it issues `TRUNCATE ... links ... CASCADE`, which silently wipes
all 230k+ check results. Until now this has not been triggered but it will be on the
next rebuild.

Additionally, after a rebuild all `link_id` values in `link_check_results` are stale
(SERIAL IDs reset), so the inner join `JOIN links l ON l.id = lcr.link_id` used by
the link status page returns zero rows — the page appears empty even though check
data exists.

## Fix

Two steps, in order:

### Step 1 — Migration: drop the FK constraint

Create `0017_drop_link_check_fk.py`. The migration drops the FK entirely, leaving
`link_id` as a plain integer primary key with no `REFERENCES` clause. No cascade,
no delete propagation.

```sql
-- up
ALTER TABLE link_check_results DROP CONSTRAINT link_check_results_pkey;
ALTER TABLE link_check_results ADD PRIMARY KEY (link_id);
-- (dropping the column constraint also drops the FK; re-adding as plain PK)
```

Or more directly, drop just the FK:

```sql
ALTER TABLE link_check_results
    DROP CONSTRAINT IF EXISTS link_check_results_link_id_fkey;
```

The Django model state change removes `on_delete=CASCADE` from the `OneToOneField`
(change to `on_delete=DO_NOTHING`, or convert to a plain `IntegerField` since the FK
is no longer enforced at DB level).

After this migration, a `TRUNCATE links CASCADE` will no longer touch
`link_check_results`.

### Step 2 — Sync step in `check_links.py`

Add a `sync_link_ids(db)` function (and call it at the top of `_main`, before
`load_urls`) that re-aligns `link_check_results` with the current `links` table by
URL. Run this after every rebuild, and also at the start of every check run so the
script is self-healing.

Three SQL statements in order:

**a. Re-sync stale `link_id`s by URL match**

```sql
UPDATE link_check_results lcr
SET link_id = l.id
FROM links l
WHERE l.url = lcr.url
  AND l.url IS NOT NULL
  AND lcr.link_id <> l.id
```

Covers the common case: same URL exists in the new `links` table under a new ID.

**b. Delete rows that are now orphaned**

```sql
DELETE FROM link_check_results
WHERE link_id NOT IN (SELECT id FROM links)
```

Removes rows whose `link_id` was not re-synced in step (a) — these are either
blank-URL links from the old build (no URL to match on) or links whose dataset was
removed entirely. They will be re-inserted as fresh pending rows by
`_populate_link_check_results` on the same run.

**c. Insert pending rows for links not yet covered**

This is the existing `_populate_link_check_results` call — no change needed. It
inserts a row for every `links.id` not already present, with `checked_at = NULL`.

### Blank-URL links after a rebuild

Blank-URL links lose their `url:blank` check result on a rebuild (deleted in step b,
re-inserted as pending in step c). They are immediately re-marked as `url:blank` by
`_mark_blank_url_links`, which runs right after `_populate_link_check_results`. Net
effect: one extra "pending → skipped" cycle; no meaningful data loss.

## What the link status page sees while stale (before sync runs)

If `build_db` has run but `check_links` has not yet been called:

- The `JOIN links l ON l.id = lcr.link_id` inner join returns **zero rows** —
  the page shows "Link status (0)".
- `LINK_ERRORS_STATS` (no join to `links`) still returns the old aggregate
  counts — confusing mismatch.
- The check-progress page joins on `l.url = lcr.url` so it still works.

Mitigation: call `sync_link_ids` from `build_db` at the end of a full rebuild,
or document that `just check-links` must be run after `just build-db`.

## Order of work

1. Write and apply migration `0017_drop_link_check_fk.py`
2. Add `sync_link_ids(db)` to `scripts/check_links.py` and call it from `_main`
3. Update the Django model (`LinkCheckResult`) to remove the cascade
4. Optionally: call sync from `build_db` or add a note to the `justfile`
5. Verify: run a test rebuild against a copy of the DB, confirm check results survive

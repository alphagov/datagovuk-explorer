# Refactor: key link_check_results on URL

**Status: implemented.**

## The problem

`link_check_results` is keyed on `link_id` (one row per resource), but
checking happens per URL — many resources share the same URL. This creates
two problems:

1. **Redundant data.** 50 resources pointing to `https://example.com/data.csv`
   produce 50 identical result rows. `write_result()` already bulk-updates
   with `WHERE url = ?`, which is why the `url` column is duplicated and
   separately indexed.

2. **Sync dance after rebuild.** `build-db` rebuilds `links` from scratch, so
   link IDs change every time. Three functions (~60 lines, 3 SQL statements)
   exist solely to re-associate check results with the new IDs:

   - `_populate_link_check_results` — insert a pending row per link
   - `_carry_over_check_results` — copy results from stale-ID rows to new
     rows, matching by URL
   - `_delete_orphan_rows` — remove the now-orphaned stale-ID rows

   This is fragile and unnecessary if the table is keyed on URL.

## The idea

Re-key `link_check_results` on **url** (one row per unique URL). The link
status report becomes a query on `links LEFT JOIN link_check_results ON url`.

Two wins:

- **Drop the sync code.** `link_check_results` no longer references link IDs
  at all, so rebuilding `links` doesn't invalidate it. The populate / carry-over
  / orphan-delete dance goes away entirely.

- **"No URL" rows still appear.** Because the report starts from `links`
  (LEFT JOIN), resources with blank/NULL URLs show up as rows with NULL status
  columns — no special `url:blank` sentinel rows needed.

## Current state

### Schema

`link_check_results` today (migration 0016):

| Column | Type | Notes |
|---|---|---|
| **link_id** | INTEGER PK | was FK → links; FK dropped in 0017 |
| url | TEXT | copy of links.url, indexed |
| checked_at | TEXT | NULL = pending |
| method | TEXT | HEAD / GET / PLAYWRIGHT / SKIPPED / ERROR |
| ok | BOOLEAN | |
| http_status | INTEGER | nullable |
| final_url | TEXT | after redirects |
| error | TEXT | prefixed: ssl: dns: timeout: etc. |

### Queries already joining on URL (no change needed)

- `check_progress.py` — `FROM links l LEFT JOIN link_check_results lcr ON l.url = lcr.url`
- `organisations.py:293` — `JOIN link_check_results lcr ON l.url = lcr.url`

### Queries joining on link_id (need updating)

- `link_errors.py:21` — `JOIN links l ON l.id = lcr.link_id` (the link
  status report — main table, facets, stats, per-org broken count)
- `reports.py:370+` — suspicious redirects report, all SQL strings use
  `JOIN links l ON l.id = lcr.link_id`

### check_links.py sync code (to be removed)

Lines 366–394: `_POPULATE_SQL`, `_CARRY_OVER_SQL`, `_DELETE_ORPHANS_SQL`
Lines 520–543: `_populate_link_check_results`, `_carry_over_check_results`,
`_delete_orphan_rows`
Lines 729–739: startup calls in `_main`

### check_links.py mark functions (updated)

`_MARK_BLANK_SQL` — removed (blank URLs have no row to key on; report derives
"No URL" from `l.url IS NULL OR l.url = ''`).

`_MARK_MALFORMED_SQL`, `_MARK_UNCHECKABLE_SQL` — changed from UPDATE to
INSERT ON CONFLICT DO NOTHING upserts, selecting distinct URLs from `links`.

### check_links.py dead-host marker (updated)

`_DEAD_HOST_SQL` — changed from `WHERE link_id IN (SELECT id FROM links WHERE
host = %s)` to `WHERE url IN (SELECT DISTINCT url FROM links WHERE host = %s)`.

## Proposed changes

Since no other environment has migrated, we can rewrite migrations 0016 and
0017 in place.

### 1. New schema (rewrite migration 0016)

```sql
CREATE TABLE link_check_results (
    url         TEXT PRIMARY KEY,
    checked_at  TEXT,
    method      TEXT,
    ok          BOOLEAN,
    http_status INTEGER,
    final_url   TEXT,
    error       TEXT
);
```

No `link_id` column. No url index needed — `url` is the PK. Drop migration
0017 (it only existed to drop the FK on link_id).

### 2. Model

```python
class LinkCheckResult(models.Model):
    url = models.TextField(primary_key=True)
    checked_at = models.TextField(blank=True, null=True)
    method = models.TextField(blank=True, null=True)
    ok = models.BooleanField(blank=True, null=True)
    http_status = models.IntegerField(blank=True, null=True)
    final_url = models.TextField(blank=True, null=True)
    error = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "link_check_results"
```

### 3. check_links.py

**Remove entirely:**
- `_POPULATE_SQL`, `_CARRY_OVER_SQL`, `_DELETE_ORPHANS_SQL`
- `_populate_link_check_results`, `_carry_over_check_results`,
  `_delete_orphan_rows`
- The three startup calls in `_main` (lines 729–739)

**Simplify `_MARK_BLANK_SQL` / `_MARK_MALFORMED_SQL`:** These currently mark
rows in `link_check_results`. After the refactor there's no row for a blank
URL (since there's nothing to key on). Two options:

Blank/NULL URLs have nothing to key on, so they simply have no row. The
report starts from `links` (LEFT JOIN), so they still appear — the category
expression derives "No URL" from `l.url IS NULL OR l.url = ''` instead of
from `lcr.error = 'url:blank'`. The `_MARK_BLANK_SQL` function goes away.

**`_MARK_MALFORMED_SQL` / `_MARK_UNCHECKABLE_SQL`** — still needed for
malformed and non-HTTP URLs (`ftp://`, typo schemes). These have a real URL
string, so they get a `link_check_results` row keyed on that URL with
`method = 'SKIPPED'` and the appropriate error prefix, exactly as now. Since
`checked_at` is set, `load_urls` skips them naturally. Just change the SQL
from UPDATE to an upsert (`INSERT ... ON CONFLICT (url) DO UPDATE`).

**`load_urls`** — currently reads `SELECT DISTINCT url FROM link_check_results
WHERE checked_at IS NULL`. After the refactor, unchecked URLs are those in
`links` that have no row in `link_check_results` (or whose row has
`checked_at IS NULL` for uncheckable marks):

```sql
SELECT DISTINCT l.url
FROM links l
LEFT JOIN link_check_results lcr ON l.url = lcr.url
WHERE l.url IS NOT NULL
  AND l.url LIKE 'http%%'
  AND lcr.checked_at IS NULL
```

Or simpler, since `write_result` already does `INSERT ... ON CONFLICT (url) DO
UPDATE`, we can keep using `link_check_results` as the source of truth for
what's been checked — just ensure new URLs get inserted. Actually, the cleanest
approach: `load_urls` queries `links` directly for distinct HTTP URLs, minus
those already checked in `link_check_results`:

```sql
SELECT DISTINCT l.url
FROM links l
WHERE l.url IS NOT NULL
  AND l.url LIKE 'http%%'
  AND l.url ~* '^https?://[^/]'
  AND l.url NOT IN (
      SELECT url FROM link_check_results WHERE checked_at IS NOT NULL
  )
```

**`write_result`** — change `_UPDATE_BY_URL_SQL` to an upsert:

```sql
INSERT INTO link_check_results (url, checked_at, method, ok, http_status, final_url, error)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (url)
DO UPDATE SET checked_at = EXCLUDED.checked_at,
              method     = EXCLUDED.method,
              ok         = EXCLUDED.ok,
              http_status = EXCLUDED.http_status,
              final_url  = EXCLUDED.final_url,
              error      = EXCLUDED.error
```

### 4. link_errors.py (link status report)

Flip the join direction. Currently:

```
FROM link_check_results lcr
JOIN links l ON l.id = lcr.link_id
```

Becomes:

```
FROM links l
LEFT JOIN link_check_results lcr ON l.url = lcr.url
```

The `LEFT JOIN` is what preserves rows for links with no URL or unchecked
links.

The category expression changes slightly: `WHEN lcr.error = 'url:blank'`
becomes `WHEN l.url IS NULL OR l.url = ''` (these have no status row).
Malformed and uncheckable URLs still have `link_check_results` rows with
`error = 'url:malformed'`, so those CASE branches stay the same. The rest
of the CASE still reads `lcr.ok`, `lcr.http_status`, `lcr.error`.

Stats (total / errors / resolved) change from counting `link_check_results
WHERE checked_at IS NOT NULL` to counting from `links LEFT JOIN
link_check_results`. This preserves per-link-occurrence semantics (N resources
sharing a URL count as N in the totals, not 1). Blank-URL links count as errors.

### 5. reports.py (suspicious redirects)

Same join flip:

```
FROM links l
JOIN link_check_results lcr ON l.url = lcr.url
```

Inner join is fine here — suspicious redirects only apply to checked links.

### 6. Migration cleanup

Since no other env has migrated:

- **Rewrite 0016** to create the url-keyed table (simple `CREATE TABLE`
  with `url TEXT PRIMARY KEY`). Remove the `IF NOT EXISTS` upgrade path from
  the old url-keyed schema — that was a one-time migration from a previous
  schema that no longer matters.
- **Delete 0017** (drop FK) — no FK to drop.
- **0018** (drop_link_errors) is unrelated; leave it.

## Files touched

| File | Change |
|---|---|
| `explorer/models.py` | Rewrite `LinkCheckResult` — drop `link` field, make `url` the PK |
| `explorer/migrations/0016_link_check_results.py` | Rewrite: simple url-keyed table |
| `explorer/migrations/0017_drop_link_check_fk.py` | Delete |
| `scripts/check_links.py` | Remove sync code; update mark/load/write/dead-host SQL |
| `explorer/queries/link_errors.py` | Flip join direction; update category expr |
| `explorer/queries/reports.py` | Flip join in suspicious-redirects SQL |
| `explorer/queries/check_progress.py` | No change (already joins on url) |
| `explorer/queries/organisations.py` | No change (already joins on url) |

## Risks and edge cases

- **Multiple resources, same URL, different result?** Not possible — one URL
  produces one check result. The current schema stores N identical copies;
  the new schema stores one. The LEFT JOIN fans it back out for the report.

- **Blank/NULL URLs.** There are links with `url = ''` or `url IS NULL`. Under
  the new schema these have no `link_check_results` row. The report handles
  them via `WHEN l.url IS NULL OR l.url = ''` in the category expression.
  Two distinct blank-URL links won't collide since they simply have no status
  row at all.

- **`--force` re-check.** Currently reloads all URLs from
  `link_check_results`. After refactor, load from `links` instead (all
  distinct HTTP URLs), ignoring what's in `link_check_results`.

- **Table size.** Goes from ~1.3M rows (one per resource) to ~750K (one per
  distinct URL). Smaller table, simpler index, faster checks.

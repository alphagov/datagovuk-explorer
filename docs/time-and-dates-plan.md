# Time and dates: replace text timestamps with real types

> **Living document — updated at the end of the first implementation session.**
> Phase 0+1 are done (uncommitted). See [Status](#status) for what landed,
> [Corrections to this plan](#corrections-to-this-plan) for what
> implementation changed, and [Next session](#next-session) to resume.

## Status

**Landed in the working tree (`HEAD` = `eb957aa`, nothing committed yet):**

- **Phase 0 — bridge.** `explorer/helpers.py::format_date` accepts
  `str | datetime | date`, converting aware values to UTC. The timezone-trap
  regression test lives in the new `tests/test_migrations.py`.
- **Phase 1 — datasets.** `metadata_created` / `metadata_modified` →
  `DateTimeField`; migration `0007_dataset_timestamps` (drops + recreates
  `mv_org_aggregates`, `AT TIME ZONE 'UTC'` conversion); `EXTRACT(YEAR …)::text`
  year facets; `order_by(..., nulls_last=…)`; `org_last_published_years` and
  `dashboard._active_card` read `.year`; the pipeline session is pinned to UTC.

**Local dev DB is migrated** (`0007` applied): both columns are `timestamptz`,
`mv_org_aggregates.last_published` is `timestamptz`, the date btrees were
rebuilt by the ALTER, and **year-facet counts are byte-identical to before**.

**Verified:** `tests/test_migrations.py` passes (all input shapes plus a full
forward→reverse→forward round-trip); full suite **414 passed** (one pre-existing
failure, below); `just test-live` **3 passed**; live query-layer checks of
`/datasets` created-year facets, `/organisations` last-published facets, both
date sorts, the report sort, and the dashboard card; a fresh `migrate` →
`ingest_ckan` on a throwaway DB produced byte-identical instants.

**Files touched this session:** `explorer/models.py`,
`explorer/migrations/0007_dataset_timestamps.py` (new), `explorer/helpers.py`,
`explorer/sort.py`, `explorer/queries/datasets.py`, `organisations.py`,
`reports.py`, `dashboard.py`, `explorer/views/reports.py`, `scripts/db.py`,
`conftest.py`, `tests/conftest.py`, `tests/test_migrations.py` (new),
`explorer/tests/test_unit_helpers.py`, `explorer/tests/test_unit_sort.py`.

**Known pre-existing problems (not caused by this work):**

- `tests/test_get_harvest_sources.py::test_error_paths` fails on `main`
  (expects `RuntimeError`, script raises `httpx.HTTPError`).
- `just lint` is already red locally (gunicorn imports, a stale noqa, formatter
  drift) — likely a newer ruff than the code was last formatted with. This work
  adds **no new** lint/format findings.
- Local `pg_dump` is 17.4 against a 18.6 server, so `just dump-db` can't run
  until the client is upgraded.

**Next:** Phase 2 (Organisations) — see [Next session](#next-session).

## Corrections to this plan

Implementation found the following. Where the plan text below still says
otherwise, **this section wins**.

1. **Django's own connections already run in UTC.** `settings.TIME_ZONE` is
   `"UTC"`, and Django's Postgres backend pins the session
   (`_configure_timezone` → `SET TIME ZONE`) for ORM *and* migration
   connections. The plan's `Europe/London` premise is the *server default*,
   which **raw psql/psycopg** connections inherit. Consequences:
   - The migration's `AT TIME ZONE 'UTC'` is still right (keeps the migration
     independent of `settings.TIME_ZONE`) but is belt-and-braces, not the only
     thing preventing a shift.
   - The **actual** one-hour-shift risk is the **raw-psycopg pipeline**, which
     the plan listed under "no changes required".
2. **The pipeline did need a change.** `scripts/db.py::connect()` now runs
   `SET TIME ZONE 'UTC'`, so every script writes naive ISO strings as UTC.
   Proved on a throwaway DB: without it, summer timestamps land an hour early
   (438 live rows are the visible class — a BST date at 00:00–00:59 UTC). No
   script uses SQL date functions (`now()`, `::date`), so the pin is safe.
3. **`AlterField`'s generated SQL (checked in installed Django 6.1).**
   `_using_sql()` hardcodes `USING %(column)s::%(type)s` with no hook to
   customise it. `SeparateDatabaseAndState` is still required — because the
   hand-written `mv_org_aggregates` is in the way, and to keep the cast
   independent of session settings — but not because Django would implicitly
   cast under `Europe/London`.
4. **Forward-only migrations from here.** Decision: no `reverse_sql` for
   phases 2+, and the project will squash migrations when done. An
   irreversible `RunSQL` fails loudly on `migrate explorer <prev>`; a *failed*
   forward migration still rolls back atomically. Phase 1's reverse is left in
   place (already written/tested) but is **not** a template for later phases.
5. **`dashboard._active_card` needed more than `.year`.** The last-published
   card builds a `?last_published_year=` URL, so the years must stay strings:
   `str(d.year)` / `str(lp.year)`, not raw ints.
6. **Fixture seed must pass aware datetimes.** `conftest.py::_model_fields`
   now converts the fixture's date-only/naive strings to aware UTC (`_utc`),
   because a naive datetime handed to the ORM would be interpreted in the
   session timezone.

## Summary

Every timestamp in the database except `link_check_results.checked_at` is
stored as `text`. The app works around this with `substr()` year extraction,
lexicographic `ORDER BY`, a duplicated `links.year_created` column, and a
Python date parser (`explorer/helpers.py::format_date`). The formats are
already inconsistent between tables, so the workarounds are load-bearing and
fragile.

This plan converts those columns to `timestamptz` (or `date` for
date-only values), deletes the derived `links.year_created` column, and
simplifies the query/render layer. The app is read-only against a build-time
snapshot, so the migration runs once against each environment and the ingest
scripts mostly keep passing ISO strings (Postgres parses them on insert).

It is phased by user-facing slice, not landed as one migration — see
[Phasing](#phasing). Each phase is its own PR with models + migration + query +
template + test changes together.

## Current state

| Table | Column | Type | Observed format |
|---|---|---|---|
| `datasets` | `metadata_created` | text | `2010-02-09T16:02:42.310217` |
| `datasets` | `metadata_modified` | text | `2026-10-02T22:00:58.469842` |
| `organisations` | `created` | text | `2012-06-27T14:48:37.434237` |
| `links` | `created` | text | `2012-06-28T10:00:55.173290` |
| `links` | `year_created` | text | `2016` (derived from the dataset, not the link) |
| `harvest_sources` | `created` | text | `2011-06-03 10:47:22.294146` (space separator) |
| `harvest_sources` | `last_run` | text | `2012-07-05 13:18:33.975723` (space separator) |
| `reviews` | `created_at` | text | `2026-09-29T15:31:55.505Z` (trailing `Z`) |
| `suggestions` | `created_at` | text | `2026-09-29T19:21:50.014Z` (trailing `Z`) |
| `collection_pages` | `page_last_updated` | text | `2026-03-24` (date only) |
| `link_check_results` | `checked_at` | **timestamptz** | already correct |

### Why this is a problem (not just aesthetics)

1. **Lexicographic sort is not chronological.** `ORDER BY d.metadata_created`
   (`explorer/queries/series.py:49`) and the text btree index
   `idx_datasets_created` only work because `datasets` happens to be uniformly
   `T`-separated. `harvest_sources.created` is space-separated (`0x20` sorts
   before `T`), so mixing sources would sort wrong at the same second.
2. **Year facets are `substr`.** `substr(metadata_created, 1, 4)` in
   `datasets.py:378`, `organisations.py:77`/`217`, and a defensive guard
   `substr(o.created, 1, 4) ~ '^\d{4}'` (`organisations.py:128`) that exists
   only because text can't guarantee a shape.
3. **`links.year_created` is a denormalised duplicate.** Set from
   `ds["metadata_created"][:4]` in `scripts/ingest_ckan.py:635`, carrying its
   own index (`idx_links_year`) and filter clause (`links.py:60`).
4. **Sorting falls back to strings.** `DATASETS_SORT["metadata_created"] =
   "COALESCE(d.metadata_created, '')"` (`datasets.py:32`) — the `COALESCE`
   exists only to make text sorting safe; a real type replaces it with proper
   `NULLS LAST` handling in `order_by()`.
5. **A hand-rolled parser.** `format_date` exists to coerce text at render
   time; its docstring even claims "DB timestamps are naive UTC
   (`timestamp without time zone`)" — a claim the schema doesn't support.
6. **No date arithmetic.** Nothing in `explorer/queries/` casts a timestamp;
   there is no way to filter "modified in the last 30 days" without a cast.

`explorer/models.py:4-6` documents the text choice as deliberate
("format_date exists for a reason"), but that is circular: `format_date`
exists *because* the columns are text.

## Target model

| Table | Column | New type | Notes |
|---|---|---|---|
| `datasets` | `metadata_created` | `timestamptz` | CKAN naive UTC |
| `datasets` | `metadata_modified` | `timestamptz` | CKAN naive UTC |
| `organisations` | `created` | `timestamptz` | CKAN naive UTC |
| `links` | `created` | `timestamptz` | CKAN naive UTC |
| `links` | `year_created` | **drop** | derive from `datasets.metadata_created` |
| `harvest_sources` | `created` | `timestamptz` | space separator, naive UTC |
| `harvest_sources` | `last_run` | `timestamptz` | space separator, naive UTC |
| `reviews` | `created_at` | `timestamptz` | already UTC (`Z`) |
| `suggestions` | `created_at` | `timestamptz` | already UTC (`Z`) |
| `collection_pages` | `page_last_updated` | `date` | date only |
| `link_check_results` | `checked_at` | `timestamptz` | unchanged |

**Why `timestamptz`, not `timestamp`:** these are instants. The naive values
are UTC by convention (CKAN emits UTC), and the LLM rows carry an explicit
`Z`. A single normalised instant type removes the "is this local or UTC?"
ambiguity that `format_date` currently guesses at.

## Migration (data conversion)

The migration number is **`0007`** (`0007_dataset_timestamps` — used). The
stale `0007_harvest_sources.pyc` in `__pycache__` is not importable. Because
the column is `text`, `USING` needs a normalisation expression. Naive values
must be pinned to UTC explicitly: a naive string cast to `timestamptz` is
interpreted in the **session timezone**. That session is `Europe/London` for
raw psql/psycopg connections (the server default — the real pipeline risk),
while Django's own connections are already pinned to `TIME_ZONE=UTC`. Pin
anyway so the migration can't depend on a session setting.

```sql
-- shared conversion for a text column named <col>
CASE
  WHEN <col> IS NULL OR <col> = '' THEN NULL
  WHEN <col> ~ '(Z|[+-][0-9]{2}:?[0-9]{2})$'   -- already carries an offset
    THEN <col>::timestamptz
  ELSE <col>::timestamp AT TIME ZONE 'UTC'     -- naive => UTC
END
```

### Expressing the conversion in Django

`AlterField` **cannot** carry a custom `USING`. Django's Postgres schema
editor hardcodes `USING %(column)s::%(type)s`
(`django/db/backends/postgresql/schema.py`, `_using_sql`) and offers no hook
to change it. The conversion must be `RunSQL`, wrapped in
`SeparateDatabaseAndState` so Django's migration state still records the
typed field — the state half is exactly the `AlterField` that `makemigrations`
would generate. The generated cast isn't wrong *per se* (Django runs the
migration under `TIME_ZONE=UTC`), but `RunSQL` also lets us drop/recreate the
view and pin UTC independently of settings:

```python
migrations.SeparateDatabaseAndState(
    database_operations=[
        migrations.RunSQL(
            sql="ALTER TABLE datasets ALTER COLUMN metadata_created TYPE timestamptz "
                "USING CASE ... END",
            reverse_sql="ALTER TABLE datasets ALTER COLUMN metadata_created TYPE text "
                "USING to_char(metadata_created, 'YYYY-MM-DD\"T\"HH24:MI:SS.US')",
        ),
    ],
    state_operations=[
        migrations.AlterField(
            "dataset", "metadata_created",
            models.DateTimeField(blank=True, null=True),
        ),
    ],
)
```

### Ordering around `mv_org_aggregates`

Postgres refuses to alter a column a view depends on. Verified on the live DB:

```
ERROR:  cannot alter type of a column used by a view or rule
DETAIL:  rule _RETURN on materialized view mv_org_aggregates depends on
         column "metadata_created"
```

The view currently computes `MAX(metadata_created) AS last_published`
(`0004_mv_org_aggregates.py`). So the datasets migration must **drop it
first**, not refresh it after:

1. `DROP MATERIALIZED VIEW IF EXISTS mv_org_aggregates`
2. `ALTER TABLE datasets ALTER COLUMN … USING CASE …` (both columns)
3. `CREATE MATERIALIZED VIEW mv_org_aggregates …` + its unique index (reuse
   the definition from `0004`)

With the column typed, `MAX()` returns a `timestamptz`; no view SQL changes
beyond the recreate.

### Other notes

- `::timestamp` accepts both `T` and space separators, so
  `harvest_sources` needs no special case.
- `date`-only values (`2026-03-24`) cast to midnight UTC; for
  `collection_pages` use `NULLIF(col,'')::date` instead — no timezone applies.
- `year_created` is *not* migrated. Verify first that every value equals
  `substr(datasets.metadata_created,1,4)` for the same dataset, then
  `DROP COLUMN`. If any mismatch shows up, keep the column as a checked
  `smallint` instead.
- The tables are ~60k–220k rows, so the rewrite is seconds, not minutes — no
  `CONCURRENTLY`/batched strategy needed. Keep it one atomic migration per
  slice.
- `idx_datasets_created` / `idx_datasets_modified` are text btrees; the
  `ALTER TYPE` rebuilds them as timestamp indexes automatically — no action.

### Reverse migrations (superseded)

The project will **squash migrations** once this work lands, so reverse
migrations aren't worth maintaining. From Phase 2 on, migrations are
forward-only: `RunSQL` omits `reverse_sql`, so `migrate explorer <prev>` fails
loudly with `IrreversibleError` rather than doing something partial. A failed
forward migration still rolls back atomically (Postgres DDL is transactional).

Phase 1 (`0007`) kept its reverse because it was already written and tested —
it is not a template for later phases. Two notes for the record:

- `timestamptz` → text: `to_char(col AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US')`.
  The original plan omitted `AT TIME ZONE 'UTC'`; without it the reverse shifts
  instants whenever the session isn't UTC.
- `date` (`collection_pages`) → text: `to_char(col, 'YYYY-MM-DD')`.
- Recreate `mv_org_aggregates` around the reverse `ALTER` the same way.

The reverse is not byte-identical for `Z`/space-separated rows (they come back
in `T` form); the instant is preserved.

## Data preservation

No rows are lost, and instants are exact. The mechanics:

- **In-place rewrite, not a rebuild.** `ALTER COLUMN TYPE … USING` converts
  every existing value; no rows are inserted or deleted, so row counts are
  identical after.
- **The migration is atomic.** Django wraps it in a transaction. A value that
  fails to parse aborts and rolls back the whole statement — you get an
  error, never a half-converted table or silently dropped rows.
- **No value would fail to parse.** Two checks over all nine text columns
  found no bad values (values observed at time of writing): a character-class
  scan (zero malformed), and `pg_input_is_valid(col, 'timestamp')`, which
  flags only `harvest_sources.last_run`'s 25 empty strings — and the `CASE`
  maps those to NULL before casting, so they never reach the parser.

  | Column | empty | NULL | malformed |
  |---|---|---|---|
  | `datasets.metadata_created` / `_modified` | 0 | 0 | 0 |
  | `organisations.created` | 0 | 0 | 0 |
  | `reviews.created_at`, `suggestions.created_at` | 0 | 0 | 0 |
  | `harvest_sources.created` | 0 | 0 | 0 |
  | `collection_pages.page_last_updated` | 0 | 0 | 0 |
  | `links.created` | 0 | 6,760 | 0 |
  | `harvest_sources.last_run` | **25** | 4 | 0 |

- **Microseconds survive.** `timestamptz` keeps microsecond precision, so
  `…:42.310217` is intact.
- **`page_last_updated` loses nothing** — all 83 rows are exactly
  `YYYY-MM-DD`, no time component, so `date` is lossless.
- **`year_created` is safely droppable.** Verified on the live DB:
  `l.year_created = substr(d.metadata_created,1,4)` holds for every one of the
  218,739 links, and every link has a matching dataset. The `links` migration
  must re-assert this before `DROP COLUMN`.

Two semantic caveats — changes in *representation*, not row loss:

1. **`harvest_sources.last_run`: 25 empty strings become NULL.** Today `''`
   and NULL are both handled by `COALESCE(h.last_run, '')` in the sort, so
   nothing observable changes. If a future feature distinguishes "never run"
   from "not recorded", that distinction is gone (there is no such read now).
2. **Reverse is gone from Phase 2 on** (forward-only; see
   [Corrections](#corrections-to-this-plan) #4). Phase 1's reverse would have
   been lossy in format only — now academic.

And one deliberate behaviour change to note: moving sort expressions from
`COALESCE(col, '')` to `NULLS LAST` puts NULL/empty rows **last** ascending,
where today they sort **first**. Only `/harvesters`' `last_run` column has
such rows (4 NULL + 25 empty), so the effect is limited to that page — flag it
rather than let it surprise a reviewer.

The real safety net remains a `db/backups` dump taken before the first
deploy; everything above explains why it shouldn't be needed. **Note:** the
local `pg_dump` (17.4) can't talk to the 18.6 server, so upgrade the client
before relying on `just dump-db`/`restore-db`.

Phase 1 verified the `migrate` → `ingest_ckan` half of `fresh-db` on a
throwaway database (byte-identical instants); the full `just fresh-db`
(including the derived-table builds) is still worth running before deploy.

## Code changes

### `explorer/models.py`

- Swap the nine `TextField` timestamp declarations for
  `models.DateTimeField(blank=True, null=True)` (and `models.DateField` for
  `page_last_updated`). `year_created` is dropped, not swapped.
- Remove `Link.year_created` and its index.
- Delete the "Timestamps are TEXT" note at the top and rewrite the schema notes
  to say timestamps are real instants.
- Keep `LinkCheckResult.checked_at` as-is.

### `explorer/queries/` (raw SQL)

Replace string extraction with date functions. Two shared rules:

- **Year facets use `::text`.** Facet params arrive from the query string as
  strings and are validated with `year in valid_years`
  (`views/organisations.py:58,66`) and matched with `= ANY(%s)` where `%s` is
  a `text[]` (`organisations.py:156`). `EXTRACT` returns `numeric`, and
  `::int` yields `int`/`Decimal` — both break those comparisons. Use
  `EXTRACT(YEAR FROM col)::text`.
- **Null ordering belongs in `order_by()`.** `explorer/sort.py:23` appends the
  direction *after* the expression, so putting `NULLS LAST` in a sort
  expression produces `ORDER BY d.metadata_created NULLS LAST ASC` — a syntax
  error (verified). Keep `*_SORT` values as plain columns and teach
  `order_by()` to emit `{expr} {direction} NULLS LAST, {tiebreak}` for the
  date columns.

| File | Change |
|---|---|
| `datasets.py:32-33` | keep plain `d.metadata_created` / `d.metadata_modified`; handled by the `order_by()` NULLS rule |
| `datasets.py:135` | `substr(d.metadata_created,1,4) = %s` → `EXTRACT(YEAR FROM d.metadata_created)::text = %s` |
| `datasets.py:378,468,475` | `substr(…,1,4) AS created_year` → `EXTRACT(YEAR FROM metadata_created)::text AS created_year`, group by the same |
| `datasets.py:509` | `MAX(metadata_created)` SQL unchanged; now returns a real instant — see Python consumers below |
| `organisations.py:143-156,221-226` | **Datasets phase.** Last-published facets read `a.last_published` (a `datasets` column): `substr(a.last_published,1,4)` → `EXTRACT(YEAR FROM a.last_published)::text`; the `= ANY(%s)` text-array clause stays text. |
| `organisations.py:77,128-139,217-219` | **Organisations phase.** `substr(o.created,1,4)` → `EXTRACT(YEAR FROM o.created)::text`; drop `_YEAR_CREATED_GUARD` (type now guarantees a year). |
| `organisations.py:284-285` | keep plain `o.created` / `a.last_published`; handled by `order_by()` |
| `links.py:60-66,144-182` | delete the `year_created` builder. The facet query at `:179` is `FROM links l` with **no `d`** — add `JOIN datasets d ON d.id = l.dataset_id`, and the `year_where` fragment must reference `d.metadata_created`. Use `EXTRACT(YEAR FROM d.metadata_created)::text`. |
| `collections.py:10-14` | keep plain `c.page_last_updated`; handled by `order_by()` |
| `reports.py:41-42` | keep plain columns; handled by `order_by()` |
| `series.py:49,65` | `ORDER BY d.metadata_created DESC` now chronological (no change beyond typing) |

Facet *contracts* stay the same: the year values rendered into the UI remain
strings (`"2016"`) — that is why the SQL uses `::text`, not `::int`. Keep the
existing `str` types in the view layer (`views/organisations.py:103`,
`datasets.py:541`) so templates and query params don't change.

### Python date consumers (break on conversion)

The SQL table above is only half the surface. These read a now-`datetime` (or
`date`) value as if it were a string and will raise `TypeError`:

| File:line | Today | Breaks because | Fix |
|---|---|---|---|
| `organisations.py:106` | `r["last_published"][:4]` | `MAX(metadata_created)` is now `datetime` | `str(r["last_published"].year)` |
| `dashboard.py:35` | `{d[:4] for d in last_pub.values() …}` | same | `d.year` |
| `dashboard.py:37` | `re.fullmatch(r"\d{4}", d[:4])` | same | drop the regex; use `d.year` |
| `dashboard.py:40` | `(last_pub.get(o["slug"]) or "")[:4]` | same | `lp.year if lp else None` |
| `datasets.py:541` | `{r["year"] …}` | safe **only** because the facet uses `::text` | none, if `::text` is kept |
| `views/organisations.py:44` | `format_date(r["last_published"])` | safe via the bridge | none (bridge) |
| `views/organisation.py:72` → `organisation.html:54` | raw value to `date_short` | safe (`datetime` formats) | none |

`reviews.created_at` / `suggestions.created_at` have no Python consumers (see
Phasing #6).

### Views / templates / helpers

- `explorer/helpers.py::format_date` shrinks to formatting a `datetime`
  (`dt.strftime`), no tz guessing. Keep the `—` fallback. The `date_short`
  Jinja filter (`jinja2.py:118`) is unchanged.
- **Transitional bridge (required for phasing):** `format_date` is the only
  cross-cutting dependency — every page renders through it. While columns are
  converted slice by slice, some callers pass text and some pass `datetime`,
  so `format_date` must accept both:

  ```python
  def format_date(value):
      if isinstance(value, str):
          value = datetime.fromisoformat(value)  # legacy text column
      ...
  ```

  Delete the `isinstance` branch in the final cleanup phase once no column is
  left as text.
- `harvesters`/`harvester` templates print `source.created` / `s.last_run`
  raw (`harvester.html:54-55`, `harvesters.html:41`) — either pipe through
  `date_short` or accept Django-ish datetime repr. Prefer `date_short` for
  consistency.
- `collections.html:18` / `collection_detail.html:15` treat
  `page_last_updated` as a date; `datetime.date` renders as `2026-03-24`, so
  `date_short` still applies.

### Ingest scripts (`scripts/`)

psycopg still passes the JSON strings straight through, but Postgres parses a
naive string into `timestamptz` in the **session timezone** — so the pipeline
does need one change, done in Phase 0/1: `scripts/db.py::connect()` pins the
session to `UTC`. With that, `ds.get("metadata_created")` works unchanged.
Verify each writer:

- `scripts/db.py` — ✅ session pinned to UTC on connect.
- `scripts/ingest_ckan.py` — datasets/organisations/links inserts pass strings
  straight through. Phase 3: drop the `year_created` derivation (`:635`) and
  its column from `_link_rows` (`:579-599`) and the `INSERT` (`:503`).
- `scripts/llm/ingest_reviews.py`, `ingest_suggestions.py` — `created_at`
  values end in `Z`; `::timestamptz` accepts them (verified).
- `scripts/ingest_collections.py` — date-only string → `date`.
- `scripts/check_links.py` — already writes `checked_at` via a real type.
- Any explicit `CREATE TABLE`/`INSERT ... SELECT` in scripts that names these
  columns: grep and update. `scripts/build_metadata.py` and friends read
  `dataset_json`, not these columns.

### Tests

Done in Phase 0/1:

- ✅ `tests/test_migrations.py` (new) — inserts a naive `T`, a space-separated,
  a `Z`, a date-only, an offset, an empty and a NULL sample, asserts the
  instants, and does a full forward→reverse→forward round-trip. Uses the new
  `tests/conftest.py::migration_db_url` (a **separate** scratch DB, so
  rewinding can't disturb the shared `migrated_db_url`).
- ✅ `tests/conftest.py::_model_fields` converts fixture date/naive strings to
  aware UTC before the ORM insert.
- ✅ `explorer/tests/test_unit_sort.py` covers `order_by(..., nulls_last=)`;
  `test_unit_helpers.py` covers the `datetime`/`date` path.
- ✅ `tests/conftest.py::migrated_db_url` runs `manage.py migrate`, so script
  tests get the typed schema automatically.

No changes needed for Phase 1: `explorer/tests/test_integration_queries.py`
and `test_unit_facet_where.py` (the latter uses its own generic `substr`
builder, not the real SQL).

Later phases, as their columns convert: update `tests/test_scripts_db.py`,
`tests/test_ingest_collections.py`, `tests/test_llm_ingest_*_db.py`,
`tests/test_check_links.py` where they compare strings.

## Rollout

Each phase (see *Phasing* below) lands as its own PR containing that slice's
models + migration + query + template + test changes together — one slice is
the unit, and it must compile and pass on its own.

Per phase:

1. `just fresh-db` on a clean checkout to prove the migrate-first build works
   end to end. This is the primary path — `fresh-db` runs `migrate` before
   `ingest_ckan`, so the schema is right from the start.
2. For an existing dev DB: `just migrate`. The datasets phase drops and
   recreates `mv_org_aggregates` as part of its migration — no manual refresh.
3. `just test` (integration tests skip without a seeded fixture DB) and
   `just test-live` against the full dev database.
4. Browser-check the pages that slice owns (see the phase table).

Railway: the deploy runs `migrate` on the existing snapshot; each phase's
rewrite is short. Take a `db/backups` dump first via the existing backup path.

## Verification

Phase 1 results:

- ✅ Spot-check instants against the source: `2010-02-09T16:02:42.310217` and
  `2010-07-09T16:02:42.310217` (a BST date) both read back as the same wall
  clock in UTC, not shifted.
- ✅ Year facet counts byte-identical before/after (`substr` and `EXTRACT`
  agree when every value is ISO) — 17 buckets, 58,751 datasets.
- Concrete in-app check (the visible DST case):
  `/dataset/cabinet-office/68addaac-59ae-4230-bb67-c5a8f6a76285` renders
  **Created 01/06/2010** from `2010-06-01T00:02:04.938631`; a shifted value
  would read `31/05/2010` (438 live rows are in this class).
- ✅ Browser-check `/datasets`, `/organisations?last_published_year=…`,
  `/organisation/:slug`, a report page — all 200.
- Still to do in Phase 3: confirm `links` year facet counts match the old
  `year_created`-based counts for the same dataset. If they differ, the
  derivation assumption was wrong — stop and reconcile.

## Risks and non-goals

- **Timezone trap (highest risk).** Casting naive text directly to
  `timestamptz` uses the session timezone. For Django's own connections that
  is `TIME_ZONE=UTC` (safe); for raw psql/psycopg (the pipeline) it is the
  server default, `Europe/London`, which shifts every summer value by an hour.
  Pin explicitly in both places: `AT TIME ZONE 'UTC'` in the migration and
  `SET TIME ZONE 'UTC'` in `scripts/db.py`. The migration test is the guard.
- **`Z` vs naive mixed in one column.** Only `reviews`/`suggestions` use `Z`;
  the regex branch handles both, but a hand-written `CASE` is required — a
  plain `USING col::timestamptz` is *not* safe.
- **`AlterField` silently reintroduces the timezone bug.** Django generates
  `USING col::timestamptz` itself; the conversion must go through `RunSQL` +
  `SeparateDatabaseAndState` (see *Expressing the conversion in Django*).
- **Reverse migrations dropped.** Forward-only from Phase 2 (the project will
  squash). `migrate explorer <prev>` fails loudly; a failed forward migration
  still rolls back atomically.
- **Non-goals:** changing the pipeline's data flow (still text in JSON, still
  passthrough inserts), introducing timezone-aware display beyond UTC,
  touching `link_check_results.checked_at`, or adding new date filters. Those
  become easy *after* this lands, not part of it.

## Phasing

Do this one slice at a time rather than one big migration. The columns are
mostly independent, each slice is its own Django migration, and the app is
read-only against a build-time snapshot — no backfill or dual-write problem.
Splitting gives a reviewable diff and a page-at-a-time rollback.

A *slice* is a user-facing area, which mostly maps to one table. The coupling
that constrains the order:

- `datasets` must go **first** — it feeds `mv_org_aggregates.last_published`,
  the org last-published facets, and series ordering, so it establishes the
  pattern for the tricky cases.
- `links` must come **after** `datasets`, because `year_created` is derived
  from `datasets.metadata_created` and the new links year facet joins to it.
- `organisations` mixes `created` (orgs) and `last_published` (datasets) on one
  page, so land it directly after `datasets` to avoid a half-typed page.
- `reviews` / `suggestions` are unread by the app (written only), so they are
  optional and lowest priority.

| # | Status | Slice | Columns | Owns these pages | Notes |
|---|---|---|---|---|---|
| 0 | ✅ done | Bridge | — | all | `format_date` accepts `str`/`datetime`/`date`; timezone-trap migration test added. |
| 1 | ✅ done | Datasets | `datasets.metadata_created`, `metadata_modified` | `/datasets`, reports, series, org last-published, dashboard | Drop+recreate `mv_org_aggregates` *around* the ALTER (drop first — Postgres blocks the alter otherwise); `::text` year facets; `order_by()` NULLS rule; fix `org_last_published_years`, `dashboard.cards()`, and the org last-published facet SQL (`organisations.py:143-156,221-226`). |
| 2 | ⬜ next | Organisations | `organisations.created` | `/organisations`, `/organisation/:slug` | Org-created facet (`organisations.py:77,217-219`); drop `_YEAR_CREATED_GUARD` (`:128`); `YEARLY_ORGS`. `ORG_SORT` already plain + `nulls_last`. Forward-only migration. |
| 3 | ⬜ | Links | `links.created`; **drop** `year_created` | `/links`, `/links/errors` | Must follow #1. Add the `datasets` join to the year-facet query; `links.created` is never read in-app — convert for consistency only. Re-assert the `year_created` derivation before dropping. |
| 4 | ⬜ | Harvest sources | `harvest_sources.created`, `last_run` | `/harvesters`, `/harvester` | Fully self-contained; space-separated values; null/empty sort order change visible here. |
| 5 | ⬜ | Collection pages | `collection_pages.page_last_updated` | `/collections`, `/collection/:slug` | `date`, not `timestamptz` — no tz risk. |
| 6 | ⬜ | LLM ingest | `reviews.created_at`, `suggestions.created_at` | none | Optional. `Z`-suffixed; never read by the app. |
| 7 | ⬜ | Cleanup | — | all | Drop the `format_date` `isinstance` bridge; rewrite the `models.py` schema note; remove the text-timestamp sections from this doc; then squash migrations. |

Sequencing is additive: phases 1–6 have no order dependency on each other
except the `datasets` → `links` and `datasets` → `organisations` edges above.

## Next session

Resume at **Phase 2 — Organisations** (`organisations.created`).

- Forward-only migration (no `reverse_sql`) — see
  [Corrections](#corrections-to-this-plan) #4.
- `organisations.py:77` `YEARLY_ORGS`, `:128` `_YEAR_CREATED_GUARD` (delete),
  `:217-219` facet counts: `substr` → `EXTRACT(YEAR FROM o.created)::text`.
- `ORG_SORT` already uses plain `o.created` with `nulls_last` (done in Phase 1)
  — no sort change needed there.
- `format_date` bridge already handles `organisations.created` becoming
  `timestamptz`; `organisation.html:46` needs no change.
- `conftest.py::_model_fields` will need the same UTC conversion for
  `organisations.created` (the fixture currently writes it via the ORM).
- Re-run `just migrate`, `just test`, `just test-live`; browser-check
  `/organisations` and `/organisation/:slug`.
- Consider combining phases 4–6 (self-contained, mechanical) if fewer PRs are
  wanted.

**Do not commit Phase 1 until reviewed** — `HEAD` is still `eb957aa` and the
local dev DB already has `0007` applied.

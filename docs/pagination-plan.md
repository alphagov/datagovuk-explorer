# Pagination consolidation plan

## Target end state

- **One mechanism**: SQL `LIMIT/OFFSET` everywhere (the two Python in-memory pages become SQL).
- **One page size**: a single shared `PAGE_SIZE = 100`.
- **One computation**: a shared `paginate()` helper — every view gets the same context keys (`page`, `total_pages`, `page_size`, `start_index`, `end_index`).
- **One URL path**: the pager macro takes a base fragment the view owns — kills the `sort=undefined` bug and the hardcoded `sort=name&dir=asc` lie.
- **One count display**: `count_pager` "X–Y of Z" on every paginated page.
- **A documented policy** for what doesn't paginate.

## Policy

> Any table that can render more than **500 rows** paginates (SQL, 100/page). Smaller tables render fully and are marked with a `# small list` comment — no pager, but the same header count text.

## Current state (as analysed)

**Paginated pages — 3 page sizes, 2 mechanisms:**

| Page | Mechanism | Size | Pager URLs | Count display |
|---|---|---|---|---|
| `/datasets` (58k rows) | SQL `LIMIT/OFFSET` | 100 | `sort/dir` from view | `count_pager` "X–Y of Z" |
| `/links` (230k rows) | SQL `LIMIT/OFFSET` | 100 | `sort/dir` from view | `count_pager` |
| `/report/{key}` | SQL `LIMIT/OFFSET` | 100 | **hardcoded** `sort=name&dir=asc` | "N total" + pager, no range |
| `/metadata/{s}/{n}` (e.g. 2,300 values) | SQL `LIMIT/OFFSET` | 100 | **broken** `sort=undefined&dir=undefined` | pager only, no count |
| `/series` (4,999 rows) | SQL `LIMIT/OFFSET` | 50 | `sort/dir` from view | `count_pager` |
| `/reviews` (521 rows) | **Python slice** in memory | 50 | `sort/dir` from view | `count_pager` |
| `/suggestions` (521 rows) | **Python slice** in memory | 50 | **broken** `sort=undefined&dir=undefined` | `count_pager` |

**Unpaginated "show all" pages:**

| Page | Rows rendered |
|---|---|
| `/organisation/{slug}` | up to **5,592** (ONS) — 64 orgs have >100 |
| `/harvester/{id}` | up to **4,062** |
| `/series/{id}` | up to 238 |
| `/organisations` | 1,480 orgs |
| `/harvesters` | 557 sources |
| `/metadata` | 185 field keys |

**Key inconsistencies found:**

1. **Same content, different treatment** — `/datasets` and `/report/{key}` paginate dataset rows at 100/page, but `/organisation/{slug}` renders up to 5,592 rows on one page and `/harvester/{id}` up to 4,062.
2. **Page size 100 vs 50 with no stated rationale.**
3. **Two mechanisms with different contracts** — SQL pages fetch only the page (O(page)); `/reviews` and `/suggestions` fetch + `json.loads` every row (O(total), measured ~89ms/page at 521 rows) even though the `reviews` table already has denormalised columns (`overall`, `findability`, `metadata`, `resources`, `theme`, `tags`, `title`, `desc`, `theme_confidence`, `created_at`) that the views ignore. Tiebreaks differ too: SQL pages pin `, d.id`; the Python pages use a two-pass stable sort breaking ties on title-ascending.
4. **Broken/lying pager URLs** — `/suggestions` and `/metadata/{s}/{n}` render literal `?sort=undefined&dir=undefined&page=N`; `/report/{key}` hardcodes `sort=name&dir=asc` although reports have no sort UI.
5. **Inconsistent header count displays** — `count_pager` on 5 pages, "N total" on reports, nothing on metadata values, hardcoded "1–N of M" on organisations/harvesters, nothing on the three detail pages.

## Page-by-page decision

| Page | Rows | Now | Decision |
|---|---|---|---|
| `/datasets` | 58k | SQL, 100 | keep — move onto shared machinery |
| `/links` | 230k | SQL, 100 | keep — move onto shared machinery |
| `/report/{key}` | varies | SQL, 100 | keep — fix pager URL + count display |
| `/metadata/{s}/{n}` | ≤2.3k | SQL, 100 | keep — fix pager URL |
| `/series` | 4,999 | SQL, **50** | size → 100 via shared constant |
| `/reviews` | 521 | **Python slice**, 50 | **SQL port**, 100 |
| `/suggestions` | 521 | **Python slice**, 50 | **SQL port**, 100 |
| `/organisation/{slug}` | up to **5,592** | none | **paginate** (reuses `/datasets` SQL pattern) |
| `/harvester/{id}` | up to **4,062** | none | **paginate** (same) |
| `/organisations` | 1,480 | none | **paginate** (SQL filter/sort; aggregates stay memoised) |
| `/harvesters` | 557 | none | **paginate** (SQL filter/sort; facet counts stay Python) |
| `/series/{id}` | ≤238 | none | exempt (< 500) |
| `/metadata` | 185 keys | none | exempt (< 500) |
| `/dataset/{id}` related lists | LIMIT 20 | none | exempt (bounded by SQL) |

## Progress

| Workstream | Status |
|---|---|
| A — shared pagination core (`PAGE_SIZE`, `paginate()`) | done — `e67cfad` |
| B — pager URL fix (macros take a view-built base fragment) | done — `502f67f` |
| C — SQL port of `/reviews` | done — `0d8798b` (notes inline below) |
| D — SQL port of `/suggestions` | done — `afe23e6` (notes inline below) |
| E — org + harvester detail pagination | done — `e641c7e` (org), `3ec83ce` (harvester); `sort_datasets` deleted (notes inline below) |
| F — organisations + harvesters list pagination | done — `4683750` (harvesters), `9ff46e9` (organisations); notes inline below |
| G — tests | reviews contract-test landed with C; suggestions with D; org + harvester detail contract tests landed with E; F's pagination tests land with the F commits — harvesters landed with `4683750`, organisations with `9ff46e9`; the pager-URL `undefined` assertion still pending |

## Workstreams (in order)

### A. Shared pagination core

`views/core.py`:

```python
PAGE_SIZE = 100

def paginate(request, total, page_size=PAGE_SIZE) -> dict:
    """total_pages, clamped page, offset, start_index, end_index."""
    total_pages = max(1, math.ceil(total / page_size))
    page = min(_page_param(request), total_pages)
    offset = (page - 1) * page_size
    return {
        "page": page, "total_pages": total_pages, "page_size": page_size,
        "start_index": offset + 1,
        "end_index": min(offset + page_size, total),
    }
```

This absorbs the repeated `max(1, ceil(...))` + `min(_page_param, ...)` + offset logic in all 7 views, and unifies the two `end_index` conventions (SQL pages use `offset + len(rows)`, Python pages use `min(...)` — identical values, one source now).

- Delete the per-view `PAGE_SIZE` constants; every view calls `paginate(request, total)` and spreads the result into context.
- Note: today `page_size` is dead context (no template uses it) — keep it uniform anyway so the contract is one shape.

### B. Pager URL fix (macros)

Change `pagination`/`count_pager` (macros/_pagination.html) to take a **base fragment the view builds**, not separate sort/dir:

```
pagination(page, total_pages, base="")   # base = "?sort=..&dir=..&org=.."
```

href becomes `base + "&page=" + n` (or `?page=n` when base empty). `count_pager` mirrors it.

Callers:
- pages with sort (`datasets`, `links`, `reviews`, `suggestions`, `series`) pass `"?" + urlencode(sort/dir) + facet_qs` — effectively `facet_qs(base_params)` with `include_sort=True` (facets.py already has this).
- `reports`: base = facets only (reports have no sort — the SQL order is fixed, the URL stops pretending).
- `metadata_values`: base = `""` → clean `?page=N`.

This removes the `"undefined"` defaults entirely and the macro's "kept deliberately" wart.

### C. SQL port of `/reviews` — done (`0d8798b`)

The schema already has the columns (ingest populates `overall`, `findability`, `metadata`, `resources`; the views just never use them — and measured **0** duplicate ok rows per dataset, so the `DISTINCT ON` is purely defensive).

`queries/reviews.py`: new builder, mirroring `datasets.py`:

```sql
SELECT r.dataset_id, d.title, d.org_slug, d.org_display_name,
       r.overall, r.findability, r.metadata, r.resources
FROM (
  SELECT DISTINCT ON (dataset_id) id, dataset_id, overall,
         findability, metadata, resources
  FROM reviews WHERE ok = true ORDER BY dataset_id, id DESC
) r
JOIN datasets d ON d.id = r.dataset_id
WHERE <score facets>                      -- facet_where, 4 clauses
ORDER BY <sort expr> <dir>, LOWER(COALESCE(d.title,'')), r.id
        -- title-asc tiebreak, always; r.id pins ties on (sort key, title)
LIMIT %s OFFSET %s
```

Sort exprs preserve current Python semantics exactly:
- `overall` → `COALESCE(r.overall, -1)` (missing sorts below present)
- subscores → their own columns
- `title`/`org` → `LOWER(COALESCE(d.title/'org_display_name',''))`
- the two-pass stable sort's "ties break title-asc regardless of dir" becomes `…, LOWER(COALESCE(d.title,''))` appended unconditionally — **plus `, r.id`**, which the original sketch missed: rows tied on (sort key, title) are otherwise unpinned and reshuffle pages. `r.id` is the latest-review row id = the stable pre-order of `latest_reviews()`, so it reproduces the Python tie order exactly (the datasets builder's `, d.id` convention).
- Text-column sort inherits the same known, accepted collation divergence as the other SQL pages (Python code-point order vs Postgres locale collation — currently 4 `£`/"25,000" titles order differently). Verified identical to the old two-pass sort on all 12 sort/dir combos across all 521 rows, modulo that.

Score facets via the shared `facet_where` pattern: value → `r.<col> = %s`; `none` → `<col> IS NULL`. Facet pools: same 4 clause builders, each excluding its own group — the standard self-excluding sidebar, replacing `_score_facet_group`'s Python loops.

Count + list, `paginate()`, `count_pager` — view slims to the standard shape; `_sort_reviews`, `_score_facet_group`, `_matches_group`, `SORT_COLUMNS` lambdas die. The template's subscore cells read the flat denormalised columns (`r.findability` etc.) instead of JSON `scores.*.score`; `latest_reviews`/`get_review` stay for `/suggestions` and the dataset detail page.

### D. SQL port of `/suggestions` — done (`afe23e6`)

As specified: one builder (`suggestions_stmts(sort, dir)` in `queries/reviews.py`), the same `DISTINCT ON` dedup subquery carrying the suggestion columns (`theme`, `theme_confidence`, `tags` as JSON text, `title` = suggested title, `"desc"` — quoted, reserved word), joined to `datasets` for the current title/org/theme/tags (decision 2). Count + list only — the two 521-placeholder `IN (...)` batch queries disappear into the join.

- Sort exprs: `title`/`org`/`theme` → `LOWER(...)` — `theme` sorts on the **current** theme (`d.theme_primary`), which is what the old Python sorter used (`current_theme`), not `r.theme`; `confidence` → `CASE theme_confidence WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END` (default asc = ambiguous first, unchanged).
- Title-asc tiebreak appended unconditionally **plus `, r.id`** — same pin as C (tie order = latest-review id = the stable pre-order of `latest_reviews()`).
- The view slims to count + page + per-row decoration (`json.loads` the page's tags — a small list at 100/page — and the `theme_changed` display flag, computed on the fetched row not as a filter). `latest_reviews`/`get_review` stay for the dataset detail page.
- Verified identical to the old two-pass sort on all 12 sort/dir combos across all 521 rows, modulo the same known, accepted collation divergence as the other SQL pages — 2 title-boundary diffs, both the £/digit case (`'OVER 25K JAN 23'` vs `'Over £25k spend…'`).
- Test: `expected_suggestion_ids` rewritten as a contract test against the builder (view page == builder page), the Python sort replica deleted.

### E. Org + harvester detail pagination — done (`e641c7e` org detail, `3ec83ce` harvester detail)

As implemented: both pages now drive count + page through the `/datasets`
builder shape — `org_datasets_stmts(slug, sort, dir_)` and
`source_datasets_stmts(source_id, sort, dir_)` in `queries/datasets.py`
(`{params, count, list}`, one fixed param, the `DATASETS_SORT_EXPRS` ORDER
BY plus the `, d.id` tiebreak, LIMIT/OFFSET). The full-table
`DATASETS_BY_ORG` / `DATASETS_BY_SOURCE` fetches are deleted; both views
render via `core.paginate()` with a sort/dir-only pager base, and both
`count_pager` headers are in the templates. `harvested_count` on the org
page is a second COUNT (`AND harvested = 1`); the harvester page's
`dataset_count` is the count query. `explorer/sort.py::sort_datasets` is
deleted — org and harvester detail were its last consumers, so the plan's
two Python in-memory pages are gone. Contract tests (view page == builder
page) cover every sort column × dir, the page-2 range, pager links keeping
sort/dir, and the page clamp.

Original plan:

- `/organisation/{slug}`: replace `DATASETS_BY_ORG.all(slug)` with a count + `LIMIT/OFFSET` builder (`WHERE org_slug = %s`, `ORDER BY` from `DATASET_SORT_COLUMNS` exprs + `, d.id` tiebreak — exactly the `/datasets` builder shape, one fixed param). Drop the Python `sort_datasets`. `harvested_count` becomes a second count (`AND harvested = 1`). Template: add `count_pager` header; table unchanged.
- `/harvester/{id}`: same for `DATASETS_BY_SOURCE`; `dataset_count` currently `len(datasets)` → the count query.

### F. Organisations + harvesters list pagination — done (`4683750` harvesters, `9ff46e9` organisations)

Harvesters half, as implemented (`4683750`): `queries/harvesters.py`
gains `harvest_sources_stmts(filters, sort, dir_)` with the `{params,
count, list}` contract — the `HARVEST_SOURCES` joins with the view's
Python `_matches` rules as WHERE clauses (type/active/frequency via the
shared `facet_where` pattern) plus a **HAVING** for the datasets-count
bucket (an aggregate; boundaries from `DATASET_BUCKET_RANGES` — the same
edges as the Python bucket tests). `HARVESTER_SORT_EXPRS` ORDER BY with a
`, LOWER(h.title), h.id` tail reproducing the old stable-sort tie order
(the base fetch's `ORDER BY LOWER(h.title), h.id` — this table's
`, d.id`-style pin). `last_run` sorts on the raw ISO timestamp: the old
Python sorter sorted the *formatted* dd/mm/yyyy string (day-then-month-
then-year, not chronological), so this is a deliberate correction.

The view drives count + one page via `core.paginate()` and decorates only
the page's rows (it used to mutate the memoised full fetch in place); the
facet master lists, validation whitelists and the Python-side
self-excluding sidebar pools still run over the memoised 557-row fetch
per the original spec. The template's hardcoded `1-{{ shown }} of {{ total }}`
→ `count_pager` (the "N datasets harvested" headline moves to the
count-note line). `sort_harvesters` deleted from `explorer/sort.py` — the
list was its last consumer. Tests: `test_harvesters` rewritten as a
contract test against the builder (every sort column × dir, page-2 range
+ pager URLs keeping sort/dir, page clamp); new `test_harvesters_facets`
pins each facet's SQL count to the Python `_matches` count over the full
fetch; `test_queries.py` gains a count==list + determinism check.

Organisations half, as implemented (`9ff46e9`): `queries/organisations.py`
gains `organisations_stmts(filters, sort, dir_)` with the same `{params,
count, list}` contract — the ORGS rows LEFT JOINed to the per-org
aggregate (`_ORG_AGG` extended from last_published alone to the full
ORG_AGGREGATES triple: total_resources, total_views, last_published), the
view's Python `_apply_filters` rules as WHERE clauses (year/pubyear/
datasets via the shared `_ORG_FACET_CLAUSES`), and `ORG_SORT_EXPRS` ORDER
BY with a `, LOWER(o.display_name), o.slug` tail reproducing the old
stable-sort tie order (the base ORGS fetch's `ORDER BY
LOWER(display_name), slug` — this table's `, d.id`-style pin).
`created`/`last_published` sort on the raw ISO timestamp: the old Python
sorter sorted the *formatted* dd/mm/yyyy string (day-then-month-then-
year, not chronological), so this is the same deliberate correction as
harvesters' `last_run`. The aggregate LEFT JOIN is 1:1 per org, so the
count is a plain COUNT over the joined rows.

The view drives count + one page via `core.paginate()` and decorates only
the page's rows (`_page_row`); `_apply_filters`/`_matches_pub_year` die,
and the memoised full fetch still feeds the facet master lists, the
pub-year validation whitelist and the sidebar pools (per the original
spec). The unused `total_orgs`/`total_datasets` context vars were dropped
— no template renders them (the "N datasets harvested" headline is a
harvesters-page feature). `sort_orgs` (+ now-unused `_num_key`) deleted
from `explorer/sort.py`. The template's hardcoded `1-{{ shown }} of
{{ total }}` → `count_pager`. Tests: `test_organisations` rewritten as a
contract test against the builder (every sort column × dir, page-2 range
+ pager URLs keeping sort/dir, page clamp); new `test_organisations_facets`
pins each facet's SQL count to the Python reference count over the merged
fetch; `test_queries.py` gains `test_organisations_stmts_consistency`
(count==list + determinism); `_org_ref_pools`' `_matches_pub_year` import
inlined as the test-local `_pub_year_match`.

Original plan:

- `/organisations` — **done (`9ff46e9`)**: `organisations o LEFT JOIN (<aggregate subquery>) a` + `facet_where(_ORG_FACET_CLAUSES, filters)` + `ORDER BY <sort expr>` + `LIMIT/OFFSET`. Sort exprs for `SORT_COLUMNS` (resource_count/views/last_published come from the aggregate join). **The memoised full-table `ORG_AGGREGATES` and `all_org_rows` stay as-is** — the page still needs the full pools for the facet master lists, pub-year validation and the total-datasets headline, and the aggregate pass is already a cached build-time snapshot, so serving pages from it costs nothing. Only the *list* becomes SQL.
- `/harvesters` — **done (`4683750`)**: add WHERE clauses (type/active/frequency/datasets-bucket — the Python `_matches` rules become SQL, bucket ranges already exist in `organisations.py`) + ORDER BY (harvester sort exprs incl. `last_run`) + LIMIT/OFFSET to the `HARVEST_SOURCES` query shape; decorate only the page's rows. Facet counts **stay Python-side** over the full 557-row memoised fetch (cheap Counters, correct self-excluding pools).
- Both templates: hardcoded `1-{{ shown }} of {{ total }}` → `count_pager` — done: harvesters `4683750`, organisations `9ff46e9`.

### G. Tests

- `test_views.py` imports of `PAGE_SIZE` move to the shared constant — done with A (`e67cfad`).
- Reviews — done with C (`0d8798b`): `expected_review_ids` fetches from `reviews_stmts` (contract test: view page == builder page); the invalid-sort / page-clamp / facet tests are kept.
- Suggestions: `expected_suggestion_ids` replicates the Python sort — rewrite to fetch from the new SQL builder with D (same contract test shape) — **done with D (`afe23e6`)**: contract test against the builder (view page == builder page), the Python sort replica deleted.
- New: org detail + harvester detail pagination tests — done with E (`e641c7e`, `3ec83ce`; contract tests against the builders, every sort column × dir, page-2 range + pager URL, page clamp). Organisations + harvesters pagination tests land with F — harvesters landed with `4683750` (`test_harvesters` contract test + new `test_harvesters_facets` pinning the SQL facet counts to the Python `_matches` counts), organisations with `9ff46e9` (`test_organisations` rewritten as a contract test against the builder — every sort column × dir, page-2 range + pager URLs keeping sort/dir, page clamp — plus new `test_organisations_facets` pinning each facet's SQL count to the Python reference count and `test_organisations_stmts_consistency` count==list + determinism check); a pager-URL assertion (`/suggestions` and `/metadata/...` links contain no `undefined`, reports/metadata-values link `?page=N` only) — **still pending**; page-size assertions updated to 100.
- Keep the existing `1-100 of X` assertions on `/datasets`/`/links` (size unchanged).

## Decisions to confirm

1. **Page size 100 everywhere** — one constant, one-line change if the taller score tables feel heavy at 100.
2. **Reviews/suggestions show current dataset title/org** (join to `datasets`) rather than review-time values from the JSON — consistent with every other page; flag if you want review-time snapshots preserved. **Applied to /reviews in C and /suggestions in D** (0/521 title/org mismatches in the current data for both).
3. **500-row exemption threshold** — mechanical rule, makes harvesters (557) paginate and series detail (238) exempt.
4. **`reviews.title` naming gotcha** — the column holds the *suggested* title; the port must not conflate it with the displayed title.

## Effort/risk

- **A + B**: small, mechanical, fixes the #4 bug immediately — done (`e67cfad`, `502f67f`).
- **C + D**: medium; the biggest single behaviour change, but the schema supports it and verified no ingest dedup surprises (0 duplicate rows). Both done — C (`0d8798b`), D (`afe23e6`).
- **E**: medium, high value — the 5.6k-row org page. Done — `e641c7e` (org detail), `3ec83ce` (harvester detail).
- **F**: the largest surface (two pages move from Python-side to SQL-side filter/sort), but the clause builders and sort whitelists already exist; harvesters is the easier half — done (`4683750`), organisations to go.

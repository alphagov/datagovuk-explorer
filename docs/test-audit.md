# App-suite audit — prune before we build fixtures

Companion to `docs/test-review-plan.md`. This is a **proposal, not code**.
It decides, per test, what survives the rewrite, so the fixture world (plan
Phase 2) is sized to the target suite rather than the legacy one.

Scope: the 80 app tests — `explorer/tests/test_queries.py` (35),
`test_link_errors.py` (10), `test_views.py` (35). The pure unit suites
(`test_facets.py`, `test_facet_where.py`) are out of scope: already fast,
pure, and worth keeping as the model.

Revision 3. Guiding rule, tightening with each pass:

> **Test shared code once. A per-page test survives only when the page has
> behaviour nothing else exercises, or simply to verify the page responds.**

## Method

- **KEEP** — intent sound; port essentially unchanged (just point at the
  fixture DB). Invariants, shapes, self-exclusion, auth.
- **REWRITE** — useful intent, wrong shape/place: too big, mixes layers,
  scrapes HTML for data. Split/reduce/relocate.
- **MERGE** — subsumed with no loss by the route smoke, a shared-macro/helper
  unit test, or an existing query-layer test.
- **DROP** — redundant, live-only, or tests the wrong thing.

## Cross-cutting findings

1. **`response.context` is unavailable.** Django's Jinja2 backend does not
   fire `template_rendered`, so the test client captures no context (verified:
   `client.get(...).context is None`). We cannot assert "the view passed the
   builder's rows to the template" without scraping HTML or refactoring every
   view to `TemplateResponse`. Resolution: **data contracts at the query
   layer; views get a route smoke and macro tests only.** No production
   refactor.

2. **The shared macros are testable in isolation.** `_pagination.html`,
   `_subnav.html`, `_facet_group.html`, `_harvested_badge.html`,
   `_filter_pills.html` are Jinja2 macros we own and they render directly
   through the configured engine (verified). Every "does page X render the
   search box / More toggle / pager link / sub-nav" assertion is one macro
   test repeated per page.

3. **The page-chrome plumbing is shared, not per-page.** Every pager/toggle
   URL goes through `facets.preserve_params()` + `facets.facet_url_for()`;
   every pager through `_pagination.html`; every sub-nav through
   `_subnav.html`; every badge through `_harvested_badge.html`; every pill
   through `_filter_pills.html`; every page's arithmetic through
   `paginate()`. No page builds its own. So each is tested once.

4. **The shared helpers are pure and currently under-tested.** `paginate()`,
   `_page_param()`, `_sort_dir()` (`explorer/views/core.py`) and
   `preserve_params()`, `facet_url_for()`, `facet_qs()` (`explorer/facets.py`)
   need no DB. The facet-URL trio is not covered by `test_facets.py` today —
   the "test it once" is a new unit test.

5. **Route wiring is one coverage problem, not fifteen.** A single
   parametrized smoke over `config/urls.py` proves every view is wired and
   every template renders against seeded data.

6. **The current view tests are the fragile part, and the failures prove
   it** — they "compute from the query layer, then grep the HTML", so they
   break on whitespace, an `aria-label`, or a nav marker. Three of today's
   eleven failures are exactly that (`Search domains`, `Search publishers`,
   `_assert_report_subnav`).

7. **`db_ready` skipping is the silent-green problem the plan names.** All
   three files `usefixtures("db_ready")` and skip when the live DB is empty.
   Replaced by `@pytest.mark.django_db` against the seeded fixture.

## Summary

| file | KEEP | REWRITE | MERGE | DROP | total |
|---|---:|---:|---:|---:|---:|
| `test_queries.py` | 27 | 3 | 2 | 3 | 35 |
| `test_link_errors.py` | 5 | 5 | 0 | 0 | 10 |
| `test_views.py` | 5 | 7 | 22 | 1 | 35 |
| **total** | **37** | **15** | **24** | **4** | **80** |

`test_queries.py` survives largely intact (already invariant-shaped).
`test_link_errors.py` roughly halves. `test_views.py` collapses from 35 tests
/ 1244 lines to about **13 tests / ~350 lines**.

---

## `test_queries.py`

Rewrites are mechanical (fixture instead of live DB, drop
`LIMIT 1_000_000`). Drops are near-duplicates.

| test | decision | notes / target |
|---|---|---|
| `test_no_arg_statements_execute` | REWRITE | cheap "every fixed statement compiles and runs" smoke; drop `isinstance` ceremony. |
| `test_orgs_row_shape` | KEEP | integration. |
| `test_dataset_total` | KEEP | integration; `datasets ↔ dataset_json` 1:1 is a real pipeline invariant. |
| `test_links_stats_shape` | MERGE → `test_stats_shapes` | with `series_count_shape`. |
| `test_series_count_shape` | MERGE → `test_stats_shapes` | |
| `test_org_statements_consistency` | KEEP | integration; count == paged rows == count + row shape. |
| `test_source_statements_consistency` | KEEP | integration. |
| `test_org_detail_row` | KEEP | integration, tiny. |
| `test_datasets_stmts_count_matches_list` (×6) | KEEP | integration; fetch all rows. |
| `test_datasets_stmts_pagination` | KEEP | integration. |
| `test_datasets_tiebreak_deterministic` | KEEP | integration. |
| `test_facet_pools_total_to_list_count` (×12) | KEEP | integration; core self-exclusion invariant. |
| `test_publisher_facet_pools_partition_list_count` | KEEP | integration. |
| `test_publisher_pool_is_ordered_count_desc` | KEEP | integration. |
| `test_facet_counts_with_live_year_and_theme` | REWRITE | add the combo to the parametrized `FACET_CONSISTENCY_COMBOS`; delete the "pick from live" wrapper. |
| `test_links_facet_pool_matches_python_reference` | KEEP | integration; bucket-boundary check. |
| `test_theme_none_counts_only_theme_primary_null` | KEEP | integration; fixture must include an `''` theme row. |
| `test_org_facet_pools_match_python_reference` | KEEP | integration; Python reference is the point. |
| `test_org_facet_counts_with_live_year_and_pubyear` | DROP | redundant with the parametrized reference test. |
| `test_harvest_sources_stmts_consistency` | KEEP | integration. |
| `test_organisations_stmts_consistency` | KEEP | integration. |
| `test_links_stmts_count_matches_list` (×4) | KEEP | integration. |
| `test_links_facet_pools_total_to_list_count` | KEEP | integration; partition invariant. |
| `test_links_facet_counts_with_live_filters` | DROP | near-duplicate; only adds a non-strict "pools shrink" check. |
| `test_every_report_count_matches_list` | KEEP | integration; fetch all rows. |
| `test_every_report_deterministic_order` | KEEP | integration. |
| `test_report_facet_counts_shape` | REWRITE | assert wiring/shape, **not** "options non-empty" (fixture-dependent). |
| `test_has_api_facets_self_exclude` | DROP | the `datasets-has-api` report was removed from `REPORTS` (no multi-facet report survives), so there is no target. Dropped in Phase 4. |
| `test_series_list_stmt` | KEEP | integration. |
| `test_yearly_helpers` | DROP | type-only; low value. |
| `test_metadata_values_pagination` | KEEP | integration. |
| `test_latest_reviews_dedup_semantics` | KEEP | integration; fixture: two reviews for one dataset + one `ok:false`. |
| `test_get_review_returns_latest` | KEEP | integration. |
| `test_get_classification_is_get_review` | KEEP | move to unit. |
| `test_get_review_missing` | KEEP | integration. |

---

## `test_link_errors.py`

| test | decision | notes / target |
|---|---|---|
| `test_link_errors_stats_shape` | KEEP | integration. |
| `test_link_errors_list_shape_and_sort_whitelist` | REWRITE | integration; keep row shape + "all sorts accepted"; drop live-host ordering. |
| `test_link_errors_count_matches_list_and_deterministic` (sort×dir) | KEEP | integration; valuable. |
| `test_harvest_state_join_includes_unknown` | KEEP | integration; fixture needs a `package_id` absent from `datasets`. High value. |
| `test_link_errors_facet_pools_partition_list_count` | KEEP | integration; core invariant. |
| `test_link_errors_facet_value_matches_filtered_count` | REWRITE | integration; keep count-vs-pool, drop live assumptions (`NOT_FOUND`/`404` must exist). |
| `test_link_errors_view` | REWRITE → page-unique only | keep only what the macro/query layer can't see: resolved-row styling (`link-errors-row--ok`), the DB→state mapping (harvested/manual/unknown), the uncapped domain/publisher toggle config for this page. Badge markup and search-box markup are macro tests. |
| `test_link_errors_facet_order_follows_filtered_pool` | REWRITE | integration; fixture has a controlled publisher/category mix, so the clever SQL picker goes. |
| `test_link_errors_filters_and_pills` | MERGE | pills into the split view test / `_filter_pills` macro. |
| `test_links_page_subnav` | MERGE | `_subnav` macro test. |

---

## `test_views.py` — route smoke + shared units + a little behaviour

A per-page test survives only if the page has unique behaviour; otherwise the
page is covered by the route smoke and the shared code by one unit test.

### A. One parametrized route smoke (respond-only)

`test_integration_routes.py`: every URL in `config/urls.py` returns 200 —
fixture ids for dynamic routes, `?q=` for search, `/report/<key>` parametrized
over `REPORTS`. Optionally add one non-default `?sort=&dir=` and one
`?page=2` variant per sortable route, still asserting **only** that the page
responds (exercises the branch without asserting order). No content
assertions here.

**Subsumes (MERGE, 14):** `test_home`, `test_every_report`,
`test_report_unknown_key_404`, `test_organisations`,
`test_organisations_facets`, `test_organisation_detail`, `test_harvesters`,
`test_harvester_detail`, `test_links`, `test_datasets`, `test_metadata_pages`,
`test_series_pages`, `test_reviews`, `test_suggestions`.

### B. Shared machinery — unit-tested once

`test_unit_view_helpers.py` (no DB, no client): `paginate()`,
`_page_param()`, `_sort_dir()`.

`test_unit_macros.py` (render each macro once through the Jinja2 engine):
`_pagination.html`, `_subnav.html`, `_facet_group.html`,
`_harvested_badge.html`, `_filter_pills.html`.

`test_facets.py` (kept) **plus** the facet-URL helpers currently uncovered:
`preserve_params()`, `facet_url_for()`, `facet_qs()`.

**Subsumes (MERGE, 6):** `test_domain_facet_live_search_box`,
`test_publisher_facet_live_search_box`, `test_temporal_toggle_keeps_metadata`,
`test_publisher_facet_order_and_toggle` (toggle half),
`test_pager_urls_never_undefined` (pager base via `preserve_params` + macro).

Facet **order** is a query-layer pool-ordering property (MERGE, 3):
`test_temporal_facet_order`, `test_theme_facet_order`,
`test_links_facet_order`.

### C. Genuine page-specific behaviour — the only per-view tests kept (7)

`test_integration_view_behavior.py`:

| test | what it keeps | from |
|---|---|---|
| report facet validation | `?org=__bogus__` falls back to unfiltered; a real value filters to the builder's count | REWRITE `test_report_org_facet` |
| multi-facet report | both pills render for `?org=&api_type=` (only multi-facet report) | REWRITE `test_has_api_both_facets` |
| datasets filter validation | `?publisher=` / `?links=` bogus fall back | REWRITE `test_datasets_publisher_filter`, `test_datasets_links_filter` |
| harvester facet pools | harvesters facet counts partition the cleared list count (query-layer) | REWRITE `test_harvesters_facets` |
| harvesters headline | headline count == datasets SOURCE facet count (query-layer) | REWRITE `test_harvesters_total_matches_datasets_facet` |
| dataset detail review | "Overall X/5" renders from the fixture review | REWRITE `test_dataset_detail_with_review` |

### D. Kept as-is (unit, no DB) / dropped

`test_health`, `test_health_exempt_from_basic_auth`,
`test_basic_auth_off_in_development`, `test_production_requires_creds`,
`test_unknown_route_renders_404` → KEEP as `test_unit_middleware.py`.
`test_missing_static_renders_404` → DROP (WhiteNoise config, not our code).

### Why these MERGEs are safe

Every pager/toggle URL is built by `facets.preserve_params()` +
`facet_url_for()` and rendered by `_pagination.html` / `_facet_group.html`;
every sub-nav by `_subnav.html`; every badge by `_harvested_badge.html`;
every pill by `_filter_pills.html`; every page's arithmetic by `paginate()`.
Testing each once covers them all.

---

## Resulting target layout (plan §8)

```
explorer/tests/
  test_unit_facets.py            (existing test_facets.py, + facet-URL helpers)
  test_unit_facet_where.py       (existing test_facet_where.py)
  test_unit_middleware.py        (health/auth/404 rendering)
  test_unit_view_helpers.py      (paginate / _page_param / _sort_dir)
  test_unit_macros.py            (pagination / subnav / facet_group / badges / pills)
  test_integration_queries.py    (most of test_queries.py)
  test_integration_link_errors.py
  test_integration_reports.py    (every report: count/list)
  test_integration_routes.py     (one parametrized all-routes smoke)
  test_integration_view_behavior.py  (the small group C)
  test_live_smoke.py             (plan Phase 5)
```

## Fixture requirements implied by the KEEPs

- **`theme_primary = ''`** row — otherwise `test_theme_none_counts_only_theme_primary_null` proves nothing.
- **Two reviews for one dataset + one `ok:false`** — for `latest_reviews` dedup.
- **A `link_errors.package_id` absent from `datasets`** — for the `unknown` harvest state.
- **`link_errors` rows** spanning every category, both `to_delete`, NULL `http_status` (No response), scheme-less URLs (No URL), and a publisher/category mix where a non-global-top category leads.
- **A dataset with no links** and **one with an API** — report facets.
- **Duplicate titles within one org** and **duplicate URLs across datasets** — the two special reports.
- **Populated facet options for every faceted report** — so `test_report_facet_counts_shape` stays meaningful.
- **Known fixture ids** (org, dataset-with-review, series, harvest source, metadata key) for the route smoke.

## Things we deliberately do NOT test

Judged by "would a regression be obvious and low-risk?", these do not earn a
test:

- **View→builder sort wiring.** If a view ignored `?sort`, the column click
  visibly does nothing. The builders' ORDER BY is tested and `_sort_dir()` is
  tested; the one-line wiring between them is left to manual use.
- **Per-page facet search opt-in.** A boolean passed to `_facet_group` in the
  template; the macro test proves the box renders when asked, and which pages
  ask is visible on render.

What *does* earn coverage is a **crash** on a non-default `?sort=`/`?page=` —
that is not visible until someone hits the URL. So the route smoke includes a
non-default `?sort=&dir=` and `?page=2` case per sortable route, asserting
**only** that the page responds (no order assertion).

## Open questions

1. Filenames: I will use the §8 names above unless you object.
2. Confirm I should execute the prune now (delete/split/rename per this audit,
   reviewable as a diff before any fixture work).

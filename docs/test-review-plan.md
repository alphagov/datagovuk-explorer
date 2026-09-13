# Test review: a plan for fast, non-fragile tests

A from-scratch look at how we test this project. The goal is not a perfect
test pyramid — it's a suite that is **simple, fast, and doesn't break when
the data changes**. This doc records the problem, a target model, and a
phased migration. Nothing here is a deadline; it's a direction.

---

## 0. Status & handoff (2026-09-13)

**Read this first.** The rewrite is in progress. This doc is the design;
`docs/test-audit.md` is the per-test keep/drop/rewrite spec that drives it.
**Do not port a legacy test without checking the audit.**

### Done

| commit | what |
|---|---|
| `c8cc1d9` | **Phase 1** — markers (`integration` / `live` / `slow`), `just test` / `test-all` / `test-live`, `test_rate_limit` marked `slow`. The fast filter lives in the **justfile** (not pytest `addopts`), so bare `pytest` runs everything; `just test` runs `-m "not slow and not live"`. |
| `e0469aa` | **Audit (Phase 0) + shared unit tests (Phase 2)** — `docs/test-audit.md`, plus the "shared machinery tested once" unit tests: `test_unit_view_helpers.py`, `test_unit_macros.py`, and the facet query-string helpers in `test_facets.py`. 33 tests, no DB, all green. |
| (in progress) | **Phase 3** — root `conftest.py` with the seeded fixture world (`make_fixtures()` + a session `django_db_setup`), proven by `explorer/tests/test_integration_queries.py` (40 tests against the fixture DB). The three legacy app-test modules are gated behind the `live` marker (interim). Default `just test` is now **181 passed, 109 deselected, ~3 s**. |

Working tree last clean at `e0469aa` (Phase 3 is uncommitted at the time
of writing). Baseline before the rewrite: **235 tests, ~60 s, 11 live-data
failures.**

### Decisions since the first draft

1. **Prune before building fixtures.** The fixture world is sized to the
   target suite (the audit), not the legacy one. Revised order:
   audit → shared unit tests → fixtures → port → delete live.
2. **Test shared code once.** A per-page test survives only if the page has
   behaviour nothing else exercises, or to verify the page responds. All page
   chrome (pager, sub-nav, facet search box, badges, pills) is tested once via
   the shared macros / pure helpers.
3. **View data contracts live at the query layer, not in HTML scraping.**
4. **Route wiring is one parametrized smoke**, not one test per page.
5. **Don't test obvious visual config** (e.g. which pages opt into facet
   search). Two gaps are deliberate and recorded in the audit: view→builder
   sort wiring, and per-page search opt-in.
6. **Route smoke also hits non-default `?sort=&dir=` / `?page=2`**
   (respond-only) so those branches can't crash green.
7. **Filenames** follow the §8 layout (`test_unit_*` / `test_integration_*` /
   `test_live_*`).

### Technical findings (don't rediscover)

- **pytest-django's test DB rewrites the global default connection.** Once
  any `@pytest.mark.django_db` test runs, `setup_databases()` switches the
  default connection to `test_datagovuk_explorer` for the whole session, so
  the still-live `db_ready` tests would read the empty test DB. Live and
  fixture tests therefore cannot share one pytest invocation. Resolution: the
  not-yet-ported live tests are gated behind the `live` marker and run only via
  `just test-live`; default runs never create the test DB alongside them.
  (Verified empirically.)
- **`response.context` is unavailable.** Django's Jinja2 backend does not
  fire `template_rendered`, so `client.get(...).context is None`. Do not plan
  on asserting view context; assert query-layer data + structural markers.
  (No production refactor.)
- **Jinja2 macros are unit-testable in isolation** via
  `django.template.engines["jinja2"].from_string(...)`. `facet_group` must be
  imported `with context` (the app does this in `_layout.html`).
- **Pagination `base` is passed with a raw `&`**; autoescape renders `&amp;`
  in the href, so tests assert the escaped form.

### Next step

**Phase 4 — port the query/link_errors tests.** Convert the KEEP/REWRITE
items from `docs/test-audit.md` in `test_queries.py` / `test_link_errors.py`
to the seeded fixture DB (the first slice is `test_integration_queries.py`),
migrate facet-order assertions to the query layer, and delete the DROP items.
Then Phase 5 replaces `test_views.py` with the route smoke and the small
behaviour suite.

### Phase 3 notes (what the fixture world covers)

- **Root `conftest.py`** holds `make_fixtures()` + the `django_db_setup`
  override. It seeds inside `django_db_blocker.unblock()` after DB creation
  and is a no-op when the tables already hold rows (so `--reuse-db` never
  double-seeds).
- **Shape:** 3 orgs (alpha named, beta `display_name` NULL, gamma empty),
  16 datasets (with/without notes, short titles, duplicate titles per org,
  withdrawn wording, `theme_primary=''` and NULL rows, created years across
  the window, no-links and API rows), ~26 links (a URL shared across
  datasets, NULL/empty and scheme-less URLs, missing format/name), 18
  link_errors (every category, all three harvest states incl. a
  package absent from datasets, both to-delete values, NULL http_status), a
  harvest source with and without datasets, metadata keys/values, a series,
  and reviews including two for one dataset plus an `ok:false`.
- **`test_integration_queries.py`** proves the world: the `/datasets`
  self-exclusion pools partition the cleared list count, the `theme=none`
  semantics are checked against a deliberate `''` row, every report's
  `count`/`list` runs and is deterministic, and review dedup returns the
  latest `ok:true` record.
- **Legacy modules** (`test_queries.py`, `test_link_errors.py`,
  `test_views.py`) carry `pytestmark = [pytest.mark.live, ...]` so `just
  test` never creates the test DB alongside them. `test-views` no longer
  overrides the `client` fixture (pytest-django's bare one is enough).

---

## 1. Where we are

Current state, measured on the dev machine:

- **235 tests, ~60 s.** `just test` runs everything in one serial pass.
- **~90 % of the time is Postgres**, not Python. Profiling
  `test_every_report` showed 6.6 s of 7.6 s inside
  `psycopg connection.wait`.
- The app tests (`explorer/tests/`) read the **live dev database** — the
  full production-shaped snapshot: 66 k datasets, 299 k links, 89 k link
  errors, 614 k metadata values.
- Tests fail against that data routinely — a full run just now had
  **11 failures**, all of the form "the first row title changed", "the
  count changed", "this facet now returns no options".

### Why it's slow

The report queries use predicates Postgres can't index: `TRIM()`,
`LENGTH(TRIM(...))`, `LIKE '%…%'`, `COUNT(DISTINCT …)`, `GROUP BY` over a
host-extraction expression. Each is a sequential scan plus a sort:

| Report page | Page time | Worst query |
|---|---|---|
| `datasets-withdrawn` | 1087 ms | 362 ms (`LIKE '%…%'` on title/notes) |
| `links-duplicate-urls` | 780 ms | 435 ms (`COUNT(DISTINCT dataset_id)`) |
| `datasets-short-description` | 706 ms | 296 ms (`LENGTH(TRIM(notes)) < 80`) |
| `datasets-duplicate-titles` | 504 ms | 190 ms (`PARTITION BY lower(trim(title))`) |

And tests re-run these constantly: the facet-partition test loops 12
filter combinations × ~8 facet queries (~96 scans), and
`test_every_report_count_matches_list` pulls `LIMIT 1_000_000` rows per
report into Python. `tests/test_rate_limit.py` also sleeps ~3 s on
purpose to exercise the rate limiter.

### Why it's fragile

- **Assertions reference live data.** `test_datasets` asserts
  `'Academy School Catchments'` appears on page 1; other tests assert
  exact counts. Rebuild the DB and they fail — even though the code is
  fine.
- **No two runs see the same data.** CI, a fresh checkout, and a
  teammate's machine all differ, so a red suite tells you nothing.
- **Skips hide breakage.** The app suite skips everything if the live DB
  is empty or unreachable, so a broken setup looks like a green run.

### What's actually good (keep it)

- `tests/` (the pipeline suite) is mostly **pure unit tests** over
  hand-built inputs — no DB, no network. `test_facets.py` and
  `test_facet_where.py` are the same. These are the model to follow.
- `tests/test_scripts_db.py` uses a **throwaway scratch database**, created
  and dropped per session. That's the right idea for DB-backed tests.
- Many integration tests assert **invariants** that survive a data change
  (count == number of rows; facets partition the total). Those are the
  valuable ones.

---

## 2. Principles

1. **Fast by default.** The default `just test` should be pure unit tests
   plus a small seeded DB. Seconds, not a minute.
2. **Deterministic.** Tests own their data. Same input → same output,
   everywhere.
3. **Non-fragile.** Assert behaviour and invariants, not production
   content or exact live counts.
4. **Test the seams we own.** The raw-SQL query layer and the pipeline
   helpers are the real risk surface. That's where effort belongs.
5. **Simple over complete.** This is not a production site. Don't build a
   fixture universe or chase coverage percentages.

---

## 3. Target model: three layers

| Layer | What it covers | DB | Speed | Default run? |
|---|---|---|---|---|
| **Unit** | Pure functions, SQL *shape*, facet builders, pipeline helpers, auth/middleware | none | ms | yes |
| **Integration** | Query layer + views against a tiny seeded Postgres | fixture DB | < 10 s | yes |
| **Live smoke** | ~5 checks that the real snapshot loads and a few pages render | live DB | seconds | opt-in (`just test-live`) |

The split is the whole idea: **move the bulk of the app suite from layer 3
to layer 2, and delete assertions that only worked against live data.**

---

## 4. What to test where

| Module | Layer | Notes |
|---|---|---|
| `scripts/download_datasets.py` | unit | Already pure/mocked. Keep. |
| `scripts/fetch_harvest_sources.py` | unit | Keep. |
| `scripts/build_series.py` | unit | Keep. |
| `scripts/build_db.py` | unit | Keep pure helpers. |
| `scripts/review_suggest.py`, `embed_only.py`, `ingest_*.py` | unit | Keep. |
| `scripts/db.py` | integration | Keep the scratch-DB approach. |
| `explorer/queries/core.py` (`facet_where`, `Query`) | unit + integration | `facet_where` is pure; `Query` needs the fixture DB. |
| `explorer/queries/*.py` (datasets, links, link_errors, reports, …) | **integration** | The highest-value target: count == list, ordering, self-excluding facets. |
| `explorer/facets.py` | unit | Already. Keep. |
| `explorer/views/*` | integration + unit | One parametrized all-routes respond smoke; page-unique behaviour only (see `docs/test-audit.md`). Shared chrome (pager/sub-nav/facet/badges/pills) is unit-tested once via the macros. |
| `explorer/templates/macros/*` | unit | Render each macro once in isolation through the Jinja2 engine. |
| `explorer/middleware.py` (basic auth) | unit | Already. Keep. |
| `explorer/templates/` | integration (light) | One smoke render per view. No substring-matching whole pages. |
| Every report | unit (shape) | Every report compiles and runs `count` + `list` — cheap with a small DB. |

---

## 5. Fixture data strategy

One small, explicit dataset that every integration test shares. Small
enough to load in milliseconds, rich enough to exercise every branch.

**Shape (target ~20 datasets):**

- **3 organisations** — one with a display name, one whose display name is
  missing (tests the `COALESCE` fallbacks), one not in the org registry.
- **~20 datasets** with deliberate coverage: with/without notes, short
  titles, duplicate titles within one org, withdrawn wording, themes,
  created years spanning buckets, one with no links, one with an API.
- **~40 links** covering: multi-dataset duplicate URLs, missing URLs,
  unparseable URLs, missing format, missing name/description, multiple
  hosts/orgs/years.
- **~20 link_errors** covering every category, all three harvest states
  (harvested / manual / unknown), to-delete yes/no, NULL http_status.
- **metadata_keys/values**, **series**, **harvest_sources**, a handful of
  **reviews** (including two for the same dataset to test "latest").

**How it's loaded:**

- Use **pytest-django's test database** (created from migrations). The
  models in `explorer/models.py` own the schema, so fixtures are plain ORM
  objects — readable and type-checked. No hand-written SQL, no pipeline run.
- Add a `make_fixtures()` factory (or a few small factory helpers) in a
  shared `conftest.py`, exposed as a session/module fixture.
- Wrap DB tests in transactions (`django_db`) so writes roll back and tests
  stay isolated. The current "read the live DB read-only" hack goes away.

**Why not keep the live DB:** the live snapshot is the *only* thing making
the suite slow and flaky. A 20-row fixture answers every invariant question
the suite actually asks. The handful of behaviours that genuinely need
scale (index behaviour, planner choices) aren't unit tests — they belong in
the opt-in live smoke layer, or nowhere.

---

## 6. Tools and framework features

Most of what we need is already installed. Short version: lean on
`pytest-django` + Django's test framework, add one or two small libraries
if the seeded suite needs them, and skip the rest.

### Already available — use these first

| Tool | What it gives us |
|---|---|
| `--reuse-db` (pytest-django) | Keep the test DB between runs; only recreate on schema change. The biggest single speed win. `--create-db` forces a clean run. |
| `django_db` / `transactional_db` | Per-test transaction rollback → isolation without truncate-and-reseed. |
| `django_db_setup` + `django_db_blocker` | Seed the fixture world **once**, after DB creation, outside the per-test transaction. With `--reuse-db` it's cached across runs. |
| `client`, `rf`, `settings`, `live_server` | Django test client, request factory, settings override, in-process server. |
| `django_assert_num_queries` / `django_assert_max_num_queries` | Guard against N+1s — a weak spot for a raw-SQL layer that fires several SELECTs per page. |
| `django_capture_on_commit_callbacks` | For post-commit side effects, if we ever add them. |
| `SimpleTestCase.assertInHTML / assertContains / assertTemplateUsed / assertRedirects` | Structure-aware assertions. `assertInHTML` parses both sides, so whitespace and attribute order don't matter — exactly what the `_squash` hacks should be replaced with. |
| `--no-migrations` | Creates tables from models, skipping migrations — **but our migrations do real work** (pgvector extension, `vector(768)` column, HNSW index, FTS). Don't use it here. |

### Worth adding (small, standard)

- **factory_boy** — the standard Django factory library. Worth it once the
  fixture world grows; for ~20 objects a plain factory function in
  `conftest.py` over the existing models is simpler and dependency-free.
  Pick one approach, not both.
- **beautifulsoup4** — for DOM-structural assertions when `assertInHTML`
  isn't enough (`soup.select(".badge-harvested")`). Lightweight and
  ubiquitous. Only needed if the Phase 4 view tests outgrow `assertInHTML`.
- **pytest-randomly** — shuffles test order, exposing order-dependent
  tests. Tiny dependency, directly serves "non-fragile".
- **pytest-xdist** — parallel workers. pytest-django already creates a
  per-worker test DB (see `django_db_modify_db_settings_xdist_suffix`), so
  it's mostly a one-line change *once the seeded suite still feels slow*.
- **hypothesis** — property-based tests for the pure pipeline helpers
  (`normalize_title`, date-pattern stripping, `_translate`). No DB, very
  fast, high value.

### Skip for now

- **model_bakery / django-dynamic-fixture / mixer** — alternative factory
  libraries; a second factory concept isn't worth it.
- **freezegun / time-machine** — can't test a real-clock rate limiter.
  Better to inject the clock/sleep into `create_rate_limiter` and assert
  deterministically, then drop the 3 s sleep test.
- **syrupy / pytest-snapshot** — snapshots trade live-data fragility for
  unreviewed-diff fragility. Only for genuinely stable pipeline output
  (e.g. a generated prompt), if at all.
- **django-test-migrations** — migrations are simple and already applied;
  not where the risk is.
- **pytest-postgresql / testing.postgresql** — we already have a local
  Postgres. Revisit only if CI can't run a service container.
- **playwright / selenium** — the Django client is enough; no browser layer.

### The recipe, concretely

```python
# conftest.py — seed once, cache with --reuse-db, isolate with transactions
@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        make_fixtures()  # ORM inserts, committed once

# Per-test: @pytest.mark.django_db gives a transaction that rolls back.
```

Run `pytest --reuse-db` locally for speed; CI runs `--create-db` once.
Two caveats: keep seeded data **read-only** (a `transactional_db` test that
commits can pollute the cache), and re-run `--create-db` whenever the
schema changes.

---

## 7. Conventions (the anti-fragility rules)

**Assertions**

- ✅ Assert **invariants**: `count == len(list)`, facet pools sum to the
  unfiltered total, ordering is stable across two runs, a page returns 200.
- ✅ Assert **structure**: a row is a dict with the expected keys; a badge
  element carries the expected class; a count is rendered as `N noun`.
- ❌ Don't assert **live content** (`'Academy School Catchments' in html`)
  or **exact production counts**.
- ❌ Don't fetch `LIMIT 1_000_000` rows to compare against a count. With a
  20-row fixture, fetching all rows *is* the cheap option.

**HTML**

- Prefer the **view context / query layer** over scraping raw HTML.
- If a template detail matters, assert one small, stable fragment
  (`class="badge-harvested"`, `href="/links/errors?category=OK"`), not a
  whitespace-squashed blob of the whole page. The current `_squash`-based
  assertions are the most brittle part of `test_views.py`.
- Keep using `assertInHTML` where it genuinely validates markup structure.

**Scope (what earns a test)**

- **Test shared code once.** If a macro/helper renders it for every page,
  test it once in isolation — not per page.
- **A per-page test survives only if the page has unique behaviour, or to
  verify the page responds.** Route wiring is one parametrized smoke.
- **Don't test obvious visual config** (which pages opt into a feature). A
  regression visible the moment the page renders isn't worth a test.
- **Data contracts belong at the query layer**, not in HTML scraping
  (`response.context` is unavailable — see §0).

**Skips vs failures**

- Unit tests must **never** skip (no DB, no excuses).
- Integration tests should **fail loudly** if the test database can't be
  created when it's expected (CI), and may skip locally with a clear
  message. A suite that silently skips to green is worse than no suite.
- Gate the live layer behind an explicit marker, not a silent skip.

**Time**

- Keep exactly one timing test (`test_rate_limit`) and mark it `slow` so it
  can be excluded from the fast pass.

**Markers** (proposed)

```python
# pyproject.toml
markers = [
  "integration: needs the seeded test database",
  "live: needs the full live database (opt-in)",
  "slow: takes > 1s (excluded from the default fast run)",
]
```

---

## 8. Layout and commands

```
tests/                     # pipeline — mostly pure (stays)
explorer/tests/            # app — split by layer
  test_unit_*.py           # pure: facets, facet_where, middleware, view helpers, macros
  test_integration_*.py    # seeded DB: queries, link_errors, reports, routes, view behaviour
  test_live_*.py           # opt-in smoke
conftest.py                # shared fixture DB + factories (root)
```

```bash
just test        # fast default: -m "not slow and not live"
just test-all    # everything (pytest -m "")
just test-live   # live smoke against the dev DB (pytest -m live)
```

The marker filter lives in the **justfile**, so bare `pytest` still runs
everything (useful for a single file, risky for the whole suite — see the
connection finding in §0).

`just test` target budget: **< 15 s**. Unit < 5 s, integration < 10 s.

---

## 9. Migration plan (revised)

Incremental — each phase leaves a working, green suite. The order changed
after the audit: **prune/spec before fixtures.**

**Phase 0 — audit (done, `e0469aa`).** `docs/test-audit.md` gives every app
test its disposition (KEEP / REWRITE / MERGE / DROP) and lists the fixture
shape the KEEPs require.

**Phase 1 — markers + fast path (done, `c8cc1d9`).** Markers registered;
`just test` / `test-all` / `test-live`; `test_rate_limit` marked `slow`.

**Phase 2 — shared-machinery unit tests (done, `e0469aa`).**
`test_unit_view_helpers.py`, `test_unit_macros.py`, facet query-string
helpers in `test_facets.py`. Pure additions — nothing deleted yet.

**Phase 3 — build the fixture world (done, uncommitted).** Root
`conftest.py` with a seeded `django_db_setup` + `make_fixtures()` (ORM
inserts, committed once; no-op under `--reuse-db`). Proven by
`test_integration_queries.py` (40 tests). The three legacy app-test modules
are marked `live` (interim) so the default run does not create the test DB
alongside them.

**Phase 4 — port the query/link_errors tests.** Convert the KEEP/REWRITE
items in `test_queries.py` and `test_link_errors.py` to the fixture DB
(started: `test_integration_queries.py`); migrate facet-order assertions to
the query layer; delete the DROP items. This is where most of the 60 s
disappears.

**Phase 5 — replace the view tests.** Add `test_integration_routes.py` (one
parametrized all-routes respond smoke, incl. non-default `?sort=&dir=` /
`?page=2`) and `test_integration_view_behavior.py` (the five page-unique
tests from the audit group C). Delete the legacy `test_views.py` and the
now-subsumed per-page chrome tests.

**Phase 6 — delete the live layer + cleanup.** Remove the live-DB
`django_db_blocker` hack in `explorer/tests/conftest.py`, the interim `live`
markers on the ported modules, dead fixtures, and any test that only ever
passed against one snapshot.

**Phase 7 — live smoke.** `test_live_smoke.py` (opt-in `live` marker): the
snapshot is reachable, dashboard/reports return 200, counts non-zero.
Nothing that depends on exact content.

---

## 10. Non-goals

- No coverage-threshold gate.
- No browser/E2E (Playwright). The Django test client is enough.
- No load or performance testing.
- No fixture data that mirrors the pipeline exactly — only the branches the
  tests need.
- No xdist / parallelisation **yet**. Get fast and deterministic first;
  parallelise only if the seeded suite is still slow.

---

## 11. Open decisions

1. **Test DB lifecycle — resolved.** pytest-django's created-once test DB +
   transaction rollback. Still to verify in Phase 3: the pgvector/HNSW
   migrations run fast on an empty DB (they should; the slow part is indexing
   populated data).
2. **Where factories live — resolved.** A single root `conftest.py`.
3. **CI.** There's no CI config today. If/when we add one, it needs a
   Postgres service with pgvector. Until then `just test` is a local
   contract.
4. **Do the pipeline tests move too?** They're already fast and pure; leave
   them unless the layout unification in §8 is worth the churn.
5. **Live vs fixture in one invocation — resolved (workaround).** They cannot
   share a session (§0). The `live` marker + `just test-live` keeps them
   apart. A future option (rejected for now) is a separate `live` DB alias +
   routing in `explorer/queries/core.py`, so both could run together — not
   worth the test-only production seam.

---

## 12. Immediate next action

The first four phases are done (markers + fast `just test`, the audit, the
shared-machinery unit tests, the seeded fixture world). The next session
starts at **Phase 4 — port the query/link_errors tests**:

1. Move the remaining KEEP/REWRITE items from `test_queries.py` into
   `test_integration_queries.py`, pointed at the fixture DB (drop the
   `LIMIT 1_000_000` fetches — with a 16-row fixture, fetch all rows).
2. Port `test_link_errors.py` similarly (`test_integration_link_errors.py`),
   keeping the row-shape, count/list, self-exclusion and unknown-harvest-state
   invariants; drop the live-host ordering.
3. Delete the DROP items and remove the ported ones from the legacy
   `live` modules (which shrink each phase until Phase 6 deletes them).

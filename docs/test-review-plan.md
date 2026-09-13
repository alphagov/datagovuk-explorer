# Test review: a plan for fast, non-fragile tests

A from-scratch look at how we test this project. The goal is not a perfect
test pyramid — it's a suite that is **simple, fast, and doesn't break when
the data changes**. This doc records the problem, a target model, and a
phased migration. Nothing here is a deadline; it's a direction.

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
| `explorer/views/*` | integration | Use the Django test client against the fixture DB. Assert status + a few structural markers, not page content. |
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
  test_unit_*.py           # pure: facets, facet_where, middleware, SQL shape
  test_integration_*.py    # seeded DB: queries, views
  test_live_*.py           # opt-in smoke
conftest.py                # shared fixture DB + factories
```

```bash
just test        # fast default: unit + integration, excludes live/slow
just test-all    # everything, including slow
just test-live   # live smoke against the dev DB
```

`just test` target budget: **< 15 s**. Unit < 5 s, integration < 10 s.

---

## 9. Migration plan

Incremental — each phase leaves a working suite.

**Phase 1 — make the fast path real (small).**
Add the markers and the `just test` / `test-all` / `test-live` commands.
Mark `test_rate_limit` `slow`. Default run excludes `slow` and `live`
(nothing is `live` yet, so this is a no-op safety net).

**Phase 2 — build the fixture world.**
Add a top-level `conftest.py` with the seeded test DB and factory helpers.
Prove it with one converted query test. Add a test that the fixture loads
and every report's `count`/`list` runs against it.

**Phase 3 — port the query tests.**
Move `explorer/tests/test_queries.py` and `test_link_errors.py` onto the
fixture DB. Keep the invariant assertions; drop live-data ones. This is
where most of the 60 s disappears.

**Phase 4 — port the view tests.**
Move `test_views.py` onto the fixture DB. Replace whole-page `_squash`
assertions with structural ones. Keep one smoke check per route.

**Phase 5 — live smoke.**
Add a small `test_live_smoke.py` (opt-in): the snapshot is reachable, the
dashboard/reports return 200, counts are non-zero. Nothing that depends on
exact content.

**Phase 6 — cleanup.**
Delete dead fixtures, the live-DB `django_db_blocker` hack in
`explorer/tests/conftest.py`, and any test that only ever passed against
one particular snapshot.

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

1. **Test DB lifecycle.** pytest-django's created-once test database +
   transaction rollback is the simplest. Confirm the pgvector/HNSW
   migrations run fast enough on an empty DB (they should; the slow part is
   indexing populated data).
2. **Where factories live.** One `conftest.py` at the repo root vs.
   `explorer/tests/factories.py`. Lean root-`conftest.py` for simplicity.
3. **CI.** There's no CI config today. If/when we add one, it needs a
   Postgres service with pgvector. Until then `just test` is a local
   contract.
4. **Do the pipeline tests move too?** They're already fast and pure; leave
   them unless the layout unification in §8 is worth the churn.

---

## 12. First three things to do

If nothing else from this doc happens, do these:

1. **Add the markers and a fast `just test`** that skips `slow`.
2. **Seed a 20-dataset fixture DB** and port one query test to prove it.
3. **Delete the live-content assertions** (`'Academy School Catchments'`,
   exact counts) — they're what's failing today, and they're not testing
   the code.

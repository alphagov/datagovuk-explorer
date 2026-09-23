# Ideas

Where the project could go — near-term improvements, medium-term features,
and longer-term directions. Roughly priority-ordered within each section.

---

## Near-term

### Scale up LLM reviews

521 of ~66k datasets have been reviewed. The pipeline (`review-suggest`)
already supports concurrency and batching — the main constraint is cost
and rate limits. Reviewing by publisher priority (large orgs first, or
orgs with the worst existing metadata) would give the most signal per
call. A coverage dashboard card ("X% of datasets reviewed") would make
progress visible.

### Publisher scorecards

Aggregate quality metrics per organisation — mean review scores, % of
datasets with no description, no links, no theme, withdrawn count, link
error rate. The data already exists in the query layer; this is a new
view that rolls it up. Could live at `/organisation/<slug>/quality` or
as a summary section on the existing org page.

### Consolidate pill construction into views

Already noted in `docs/todo.md`. Some pages build filter pills in the
view (the Python approach — explicit, testable), others in the template
(fragile, depends on two variables being named consistently). Moving
everything to the view pattern eliminates a class of silent-wrong-label
bugs.

### Historical quality snapshots

The DB is a point-in-time build. Storing a timestamped summary row per
rebuild (total datasets, total with issues, per-report counts, per-org
aggregates) would let the dashboard show trends — "200 fewer datasets
without descriptions than last month". The snapshot table is small (one
row per build); the pipeline already knows the counts.

### CSV/JSON export for reports

Each report page shows a paginated table. Adding a `/report/<key>.csv`
(or `.json`) endpoint that streams the full result set (no pagination)
would let people pull the data into spreadsheets or other tools. The
query layer already has the list SQL; the view just needs an alternate
renderer. Same for `/datasets.csv`, `/links.csv`.

---

## Medium-term

### Automated pipeline

The current workflow is manual: `get-datasets`, `build-db`,
`ingest-reviews`, then dump/tunnel/restore to Railway. An automated
version could:

- Run on a schedule (weekly or nightly)
- Fetch incrementally (CKAN's `package_search` supports `fq=metadata_modified:[NOW-7DAYS TO *]`)
- Rebuild the DB in-place on Railway (skip the dump/tunnel dance)
- Post a summary to Slack or email when done

This is the biggest operational improvement. The fetch is ~9 minutes,
the build ~3 minutes — easily within a cron job or Railway cron service.

### Link checking

Done — `just check-links` runs the in-project checker (HEAD → GET →
Playwright fallback) and writes results directly into
`link_check_results`. View live progress at `/check-progress`.

### Quality change alerts

With historical snapshots in place, detect regressions: "Environment
Agency added 50 datasets with no description this week" or "link error
rate for ONS jumped from 2% to 15%". Could be a daily digest email, a
Slack webhook, or a dedicated `/alerts` page showing recent changes.

### Harvest flooding detection

The harvest-flooding-report investigation was manual. The patterns it
found (creation-date clustering, cross-org title overlap, name-slug
counter sequences) could be automated as a new report:
"publishers with suspiciously high recent creation rates" or "datasets
whose titles belong to other organisations". The data for this is
already in the DB.

### Search improvements

- **Faceted search results** — the `/search` page returns flat lists.
  Adding facets (publisher, theme, format) to search results would make
  it more useful for large result sets.
- **Semantic search as primary** — currently pgvector semantic search is
  only on the dataset detail page ("related datasets"). Promoting it to
  the main search (with a toggle or automatic fallback when FTS returns
  few results) would improve discovery for vague queries.
- **Search analytics** — log what people search for (anonymised). The
  most common queries with zero results reveal gaps.

### Dataset comparison view

When the LLM suggests a different title or description, show a
side-by-side diff — current vs. suggested — so the reviewer can see
exactly what would change. Same for theme and tags. This is the bridge
between "the LLM thinks this is wrong" and "here's what to do about it".

---

## Longer-term

### Quality API

A JSON API serving the same data the UI shows — per-dataset scores,
per-org aggregates, report results, search. This would let other tools
(data.gov.uk's own admin UI, external dashboards, CI pipelines for
publishers) consume quality signals programmatically. The raw-SQL query
layer is already structured for this — the views are thin renderers, so
adding JSON responses is mostly plumbing.

### Publisher self-service

If publishers could see their own scorecard and the specific issues
flagged for their datasets, they could fix problems without someone
manually sending them a list. This requires authentication beyond the
current basic-auth gate — possibly integration with data.gov.uk's
existing publisher accounts, or a simple invite-link system.

### Temporal coverage analysis

The temporal periods table already stores inferred coverage dates. A
dedicated report could show: datasets whose declared coverage ended more
than N years ago (possibly stale), datasets with no temporal coverage at
all (the facet exists but there's no dedicated report), and coverage gaps
within a publisher's portfolio ("you have annual crime stats for
2015–2022 but nothing for 2023").

### Cross-catalogue comparison

data.gov.uk is one of many national open data portals. Comparing
metadata quality across portals (e.g. vs. data.europa.eu,
data.gov, data.gov.au) would contextualise the scores — "UK datasets
average 3.2/5 for findability vs. 3.8 in the EU portal". This is a
large scope expansion but the review pipeline is model-agnostic and
could point at any CKAN instance.
  
---

## Technical improvements

### CI pipeline

No CI is configured. A GitHub Actions workflow running `just lint` and
`just test` (the offline pipeline tests) on every push would catch
regressions early. The app tests need a built DB, so they'd either run
against a fixture dump restored into a CI Postgres, or be split into a
separate "integration" job.

### Incremental DB updates

The current build truncates and reloads everything. For the ~66k dataset
catalogue this takes ~3 minutes, which is fine for weekly rebuilds but
blocks the path to daily or real-time updates. An incremental path —
upsert changed datasets, delete removed ones, recompute only affected
FTS/embeddings — would make frequent refreshes practical.

### Cache invalidation

The query layer uses `functools.cache` (process-lifetime memoisation),
so data is stale until the server restarts. For a build-time snapshot
this is correct, but if the DB starts getting incremental updates, the
cache needs a generation counter or a simple "clear on signal" mechanism.
Django's cache framework could back this, or a lightweight version
counter in a DB table.

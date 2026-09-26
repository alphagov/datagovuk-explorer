# Analytics consent plan

Remediation plan for `docs/ga-opt-in-analysis.md`.

The opt-in analysis is useful and its headline numbers check out, but the
document and the code it cites have drifted apart, and the per-page scaling
formula has an unbounded failure mode in production. This is the plan to fix
that, roughly in priority order.

All figures below were reproduced by running the committed scripts against the
committed data.

## Status

| Item | State |
|---|---|
| F1 / Step 2 — canonical Apr–Aug inputs | **done** |
| F8 — collection category rename | **done** |
| F3 / Step 4 — collections comparison on canonical inputs | **done** |
| F7 — period label | **done** (cross-ref and >1-rate pages remain) |
| Step 6 — doc corrections | **partial** |
| F2 / Step 1 — `consent_rate.py` histogram | **done** |
| F4 / Step 3 — scaling explosion | **done** |
| F5 — scaling assumption documented | **done** |
| F6 / Step 5 — org analysis script | open |

## Findings

### F1 — The doc does not describe the running code (high) — **fixed**

The consent rate itself is computed from just two Apr–Aug 2026 files:

- `data/console-clicks-apr-aug.csv` — Search Console clicks
- `data/ga-google-landing-apr-aug.csv` — GA Google landing sessions

`scripts/consent_rate.py` already reads exactly these two, so the consent-rate
calculation is correct. `data/ga-views-apr-aug.csv` (GA page views) is a third
Apr–Aug file, but it plays no part in the consent rate — it is needed only by
the view-count formula, which scales the non-Google component `ga_views -
ga_landing`.

The problem is on the production side. `scripts/build_db.py` and
`scripts/ingest_collections.py` compute the same per-page consent rate, but
from the full-year files (`ga-google-landing-pages.csv`, `datagovuk-pages.csv`),
and scale the non-Google component using full-year page views
(`ga-page-views.csv`). So the rates applied to user-facing view counts come
from a ~12-month window and are **not** the values documented.

**Decision: Apr–Aug is the correct window.** Production should use the three
apr-aug files — `ga-views-apr-aug.csv`, `ga-google-landing-apr-aug.csv`,
`console-clicks-apr-aug.csv` — so the consent rate and the page views it scales
are drawn from the same period.

*Done:* `scripts/build_db.py` and `scripts/ingest_collections.py` now point at
the three apr-aug files, and the `Collection` docstring in
`explorer/models.py` was corrected. Verified `load_views_csv()` → 23,298
datasets and `load_collection_views()` → 99 slugs (82 matched to collection
files) on the new inputs; `tests/test_build_db.py` passes.

### F2 — Script no longer reproduces the distribution chart (high, easy fix) — **fixed**

`scripts/consent_rate.py` is internally inconsistent:

- comment: `# Distribution (all pages with >= 50 SC clicks)`
- variable: `ratios_50`
- actual filter: `if sc[u] >= 10`
- printed label: `"pages with 10+ SC clicks"`

Running it now gives **n=2,099** and a 26-row histogram; the doc reports the
**50+** distribution (n=779, 11 rows, max band 20%+), which reproduces
separately and matches the doc. The script also uses `max_band = 0.50`, so it
prints 20–50% bands the doc collapses into `20%+`. So
`python -m scripts.consent_rate` does **not** produce the doc's chart.

Minor: the histogram bins are computed with floats
(`lo_r = i * band`, `hi_r = lo_r + band`), so adjacent boundaries can
double-count a value. The doc's bars sum to **780** for a stated n of **779** —
an off-by-one from exactly that precision issue.

*Fixed — see Step 1. The description above is the pre-fix state; the doc chart
is now regenerated from the script with the 50% cap (26 rows, n=779).*

### F3 — Collections-vs-datasets comparison is apples-to-oranges (high) — **fixed**

The collection numbers came from `scripts/ingest_collections.py`, which read
the **full-year** `ga-google-landing-pages.csv` / `datagovuk-pages.csv`, while
the dataset numbers come from the **5-month** apr-aug files, so the comparison
was confounded with period.

*Done:* both paths now use the canonical apr-aug files (Step 2), and the doc's
collections row was recomputed on them: **53 pages, 5.6% aggregate, 13.5%
median, 6.7% p25, 17.2% p75** (dataset row unchanged: 2,099 / 9.4% / 8.3% /
5.3% / 13.5%). The higher collection median survives (13.5% vs 8.3%), but the
sample is small (n=53), the aggregate still runs the other way (5.6% vs 9.4%),
and the repeat-visit explanation remains unproven — see Step 4.

### F4 — Per-page scaling explodes at low consent rates (high) — **fixed**

The doc says capping at 1.0 handles the edge case. It only bounds the *upper*
end; the multiplier `sc / ga_landing` is unbounded below. On the canonical
Apr–Aug inputs (current production path):

| total   | GA views | GA landing | SC clicks | multiplier |
|---------|----------|------------|-----------|------------|
| 42,090  | 1,092    | 149        | 5,743     | **39x**    |
| 27,930  | 6,101    | 154        | 705       | 5x         |
| 24,188  | 3,549    | 1,668      | 11,368    | 7x         |
| 18,055  | 1,167    | 104        | 1,609     | 15x        |

`e5d7c4b6…` (hmo-register5) ends up with ~42k "views" — the top dataset —
because 149 opted-in GA landings against 5,743 SC clicks gives a 2.6% rate
that is almost certainly noise, not consent.

Across the apr-aug overlap: **1,236 pages get a >10x multiplier, 66 >50x, 7
>100x, max 230x.** This materially distorts rankings, which is worse than the
flat 10x the doc rejects.

### F5 — The scaling assumption contradicts the doc's own findings (medium) — **fixed**

`non_google = ga_views - ga_landing` mixes **Views** and **Sessions** (different
units), then divides by a session-based rate. More importantly it assumes the
Google consent rate applies to direct/referral traffic — exactly the assumption
"§Why the variance" argues is false (professional vs. public visitors behave
differently). The doc should state this as an explicit assumption and note the
direction of bias (over-inflating high-consent audiences).

### F6 — Org-level tables are not reproducible (medium)

Nothing in the repo generates the "By publisher organisation" section (n=122
orgs, lowest/highest lists). It cannot be reviewed or refreshed, and there is no
org roll-up in `build_db.py`.

### F7 — Metric validity and consistency nits (low) — **partial**

- 45 of 3,903 overlap pages (1.2%) have GA landings **>** SC clicks (max 10.1x).
  These are not consent rates; the doc explains them as repeat visits but still
  includes them in the distribution (the 30.2% stdev in the 10–49 bucket is
  driven by them). **Open.**
- Period label: **fixed** — the doc now reads `2026-04-01 to 2026-09-01`
  (April – August 2026).
- `docs/google-console-analytics-compare.md` concludes **5–8%** while this doc
  says **~10%**. Different methods, but the two should cross-reference each
  other. **Open.**

### F8 — Collection category rename breaks slug matching (fixed)

Switching to the canonical Apr–Aug files exposed a rename: the collection
category `government` is now `government-and-parliament` (the only renamed
category), but the Apr–Aug GA and Search Console exports still use
`/collections/government/…`. Every `government-and-parliament/*` collection
whose data appears under `government/*` therefore matched nothing and loaded
with **0 views** (7 collections).

*Done:* `scripts/ingest_collections.py` gained a `_CATEGORY_ALIASES` map and a
`_normalise_slug()` helper that rewrites the leading category segment before
the existing `_SLUG_ALIASES` lookup. Re-running `just ingest-collections`
matches 82 of 83 collections; the remaining zero,
`government-and-parliament/parliament-voting-records`, is genuinely absent from
Apr–Aug (it only appears under the new path in the full-year export).

## Plan

### Step 1 — Fix `consent_rate.py` so it reproduces the doc — **done**

- Distribution filter changed from `>= 10` to `>= 50` (matching the comment and
  variable name).
- Float binning replaced with integer-percentage buckets
  (`int(r * 100) // 2`), so boundary values map to exactly one bucket. The bars
  now sum to the stated n.
- **Decision:** `max_band` stays at **50%** (not collapsed at 20%), so the doc
  chart was regenerated verbatim from the script: 26 rows, `10%-12%` corrected
  from 88 to **87**, and the old `20%+  40` split into `20–50%  35` + `50%+  5`.
- Acceptance: verified `diff` between
  `python -m scripts.consent_rate` and the doc chart is empty.

### Step 2 — Make Apr–Aug the one canonical analysis period — **done**

The correct inputs are fixed:

| Role | File | Used by |
|---|---|---|
| GA page views | `data/ga-views-apr-aug.csv` | view formula only |
| GA Google landing sessions | `data/ga-google-landing-apr-aug.csv` | consent rate + view formula |
| Search Console clicks | `data/console-clicks-apr-aug.csv` | consent rate + view formula |

- Point `build_db.py` and `ingest_collections.py` at these three files, so
  production and `consent_rate.py` share one source of truth.
- `consent_rate.py` already reads the two files it needs; leave it alone apart
  from the F2 fix.
- Replace the full-year constants in both loaders.
- Document the Apr–Aug period in the doc and in the script docstrings.
- Acceptance: the three apr-aug files are the only GA/SC inputs in the
  analysis and production paths; no file is read by only one of them.

### Step 3 — Stop the low-consent-rate explosion — **done**

The literal shrinkage approach (pool each rate toward the aggregate, weighted by
sample size) did not survive contact with the data: a Beta-Binomial prior
`(gl + k·p0) / (sc + k)` barely moves hmo-register5, because `sc` (5,743) is
large and dominates — `k=500` only lifts the rate 2.6% → 3.2%. Weighting by the
landing sample instead does move it, but was rejected in favour of something
simpler.

**Decision: floor the per-page rate at the corpus-wide pooled rate, ~0.10.**

```python
consent_rate = max(min(gl / sc, 1.0), CONSENT_RATE_FLOOR)
```

The pooled rate is 21,330 / 209,455 = **10.18%** (Wilson 95% CI 10.05–10.31%),
but the interval is only 0.26pp wide, so the confidence bound is inert — the
floor is what does the work. The chosen readable `0.10` caps the multiplier at
exactly **10x** (the point estimate would give 9.82x, the lower bound 9.95x — all
noise). Note the direction: flooring the rate *caps* the multiplier, so it is
conservative against over-counting. Using the upper bound (10.31%) would be
marginally more so; it was not worth the extra complexity.

Effect on the canonical Apr–Aug data:

- `e5d7c4b6` (hmo-register5) **42,090 → 15,173**, dropping to rank 3 behind two
  genuine pages.
- Max multiplier **230x → 10x**; total dataset views 1,038,875 → 815,250.
- 1,236 of 3,903 overlap pages (32%) sit below the floor and are adjusted; the
  other 2,667 keep their exact per-page rate, so high-consent pages (e.g. 50%)
  still scale 2x — this is *not* the flat 10x the doc rejects.

Trade-off: genuinely low-consent pages are overstated (by design, bounded).
Documented as an assumption in the analysis doc (F5).

Acceptance met: hmo-register5 no longer ranks top; no page exceeds a ~10x
multiplier. Regression test added:
`tests/test_build_db.py::test_load_views_csv_consent_rate_floor`.

### Step 4 — Recompute the collections comparison — **done**

Collections and datasets are now computed over the same canonical Apr–Aug
window (Step 2), and the doc's collections row was updated to **53 / 5.6% /
13.5% / 6.7% / 17.2%**. The collection median still exceeds the dataset median
(13.5% vs 8.3%). Confidence intervals for the n=53 collection sample were not
added; do so if the claim is to be relied on.

### Step 5 — Commit the org-level analysis

Add a script that rolls per-page GA landing / SC clicks up to publisher
organisation (using the `downloads/` org mapping or the `datasets` table) and
emits the tables currently hand-written into the doc.

### Step 6 — Correct the doc — **partial**

- [x] Fix the period label to Apr–Aug (now `2026-04-01 to 2026-09-01`).
- [x] Name the canonical input files in the Background and Scripts sections.
- [x] Recompute the collections row (Step 4).
- [x] Point the doc at this plan.
- [x] Add an explicit "Assumptions and limitations" section covering F5 and the
  noisy tail (max multiplier was 230x before the Step 3 floor).
- [ ] Cross-reference `docs/google-console-analytics-compare.md` and explain why
  the two estimates differ (5–8% vs ~10%).

## Rollout

Views are stored in the database (`datasets.views`, `collections.views`), not
computed at request time, so shipping the code is not enough. After deploying,
re-run both ingests against the target database:

- `just ingest-views` — resets `datasets.views` to 0 and reloads (seconds).
- `just ingest-collections` — truncate + reload `collections`; run
  `just llama-server` first if `collection_embeddings` needs rebuilding.

Locally, both were re-run against `datagovuk_explorer`; `hmo-register5` now
stores **15,173** (rank 3). Production has not been updated yet.

## Verified as correct

- Overall aggregate **10.2%**, median **8.3%**.
- "By traffic volume" table reproduces line-for-line (1,320 / 575 / 188 / 13 /
  3 pages).
- `(not set)` = **8,967** of **39,592** sessions (22.6% ≈ 23%).
- Datasets in SC 20,316 / GA landing 3,977 / both 3,903.
- The formula in the doc matches `build_db.py:575-580` and
  `ingest_collections.py:184-189`.

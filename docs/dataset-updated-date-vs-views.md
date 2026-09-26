# Dataset age / update date vs views

## Summary

We wanted to know whether **older datasets get fewer views**. They don't —
age turns out to be irrelevant. What matters (a bit) is how *recently* a
dataset was updated.

- **Age doesn't matter.** No relationship between when a dataset was created
  and how many views it gets.
- **Update recency does.** More recently updated datasets get more views.
  The effect is **moderate** — roughly a **2×** difference in typical view
  counts — but it's a **weak predictor** of any individual dataset.
- **It's about how many views, not whether you get any.** Recency doesn't
  change the odds of a dataset being discovered at all; it's associated with
  the ones already getting used getting *more* traffic.
- **It survives on manually-maintained data**, so it isn't just an artifact
  of automated harvesting.
- **We can't tell which way it runs.** Popular datasets may get updated
  *because* they're popular, rather than the other way round.

## What we measured

- **Views**: the `views` column on `datasets` — combined Google Analytics +
  Search Console traffic for a **5-month window (April–August 2026)**, not
  lifetime views. See `docs/ga-opt-in-analysis.md`.
- **Created date**: when the dataset was first published
  (`metadata_created`).
- **Updated date**: two proxies — `metadata_modified` and the last time a
  resource/link on the dataset was created (`links.created`). Neither is
  perfect (see caveats), but they agree with each other.

One thing to know up front: **views are extremely concentrated**. 67% of
datasets get zero views in the window, and the top 1% of datasets account
for **75% of all views**. So averages are misleading; we compare
distributions instead.

## Finding 1: age doesn't matter

Correlation between creation year and views is essentially zero once you
ignore datasets created in 2026 (which are brand new and mostly have no
views yet):

| dataset set | correlation |
|---|---:|
| all datasets | −0.21 |
| excluding datasets created in 2026 | −0.06 |
| datasets with views only | +0.01 |

The whole "older = fewer views" impression comes from the 2026 cohort:
14,354 datasets, mostly recent low-traffic harvests from local councils.
Remove them and there's nothing. Within individual publishers it's also nil.

**There is no evidence that older datasets attract less traffic.**

## Finding 2: update recency matters (moderately)

For datasets that got any views, correlation between view count and update
date is about **+0.13** for both proxies (near zero across all datasets,
because of the 67% sitting at zero views). It holds within publishers too.

More importantly, the whole distribution shifts. Manually-maintained
datasets that got views, grouped by when their most recent resource was
created:

| last resource created | datasets | mean views | p25 | **median** | p75 | % with 10+ views | % with 50+ views |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2019 or earlier | 2,431 | 28.5 | 1 | **3** | 7 | 18.8% | 6.1% |
| 2020–2022 | 509 | 50.9 | 1 | **3** | 13 | 28.9% | 11.4% |
| 2023–2025 | 556 | 148.4 | 2 | **6** | 24 | **41.5%** | **15.6%** |

Every part of the distribution moves, by roughly **2× to 2.6×**:

- median views: **3 → 6**
- share getting 10+ views: **19% → 42%**
- share getting 50+ views: **6% → 16%**

### Moderate effect, weak predictor

- As an **effect size** this is **moderate**: a consistent doubling in
  typical views and a ~2.5× change in the odds of being a heavily-viewed
  dataset.
- As a **predictor** it's **weak**: recency explains only ~5% of the
  differences in views between datasets. Pick two datasets at random and the
  more recently updated one has more views about **59%** of the time (50% is
  a coin flip).

Both are true because views are so variable (1 to ~28,000). Recency reliably
shifts the whole spread, but most of the difference between any two datasets
is something else — topic, publisher, demand.

## Caveats

1. **The dates are partly harvesting artifacts.** `metadata_modified` is
   heavily rewritten by automated harvesting, and many `links.created` values
   are just the pipeline's run time. That's why the manual/harvested split
   matters — the effect is *stronger* for manually-maintained datasets.
2. **Two proxies, not two independent tests.** They agree most of the time
   (correlation 0.76), so this is one signal seen twice.
3. **Direction is unresolved.** Actively-maintained datasets may be popular
   because they're maintained, or maintained because they're popular.
4. **It's a 5-month snapshot.** The `views` column is April–August 2026, not
   lifetime traffic.
5. **Absolute numbers are small.** A doubling of the median is 3 → 6 views
   over five months — meaningful for "is anyone looking at this?", less so
   for audience size.

## What we can say

- Age is not a driver of views.
- Update recency is associated with meaningfully more traffic — a moderate
  effect that holds for manually-maintained data and within publishers.
- The causal direction is unknown, and the effect is about *magnitude*, not
  *discovery*.

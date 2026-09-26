# GA cookie consent (opt-in) rate analysis

## Background

We combine three data sources to estimate dataset and collection page views:

- **GA page views** (`data/ga-views-apr-aug.csv`) — all page views recorded by Google Analytics (cookie opt-in required)
- **GA Google landing pages** (`data/ga-google-landing-apr-aug.csv`) — sessions that arrived from Google (cookie opt-in required)
- **Search Console clicks** (`data/console-clicks-apr-aug.csv`) — clicks from Google search results (no opt-in, counts every click)

The formula: `GA page views - GA Google landing sessions + Search Console clicks`

This replaces GA's count of Google arrivals with Search Console's count, which doesn't depend on cookie consent.

## The consent rate

GA only sees users who accepted the cookie banner. Search Console counts every Google click regardless. For pages that appear in both datasets, the ratio `GA landing sessions / SC clicks` approximates the consent rate.

Analysis period: 2026-04-01 to 2026-09-01 (April – August 2026, 5 months; GA functioning correctly).

**Overall: ~10% aggregate, ~8% median** — GA sees about 1 in 10-12 real Google arrivals.

### By traffic volume

| SC clicks  | pages | median | p25  | p75   | stdev | aggregate |
|------------|-------|--------|------|-------|-------|-----------|
| 10-49      | 1,320 | 9.1%   | 5.9% | 15.0% | 30.2% | 11.7%     |
| 50-199     | 575   | 6.9%   | 4.0% | 11.2% | 8.5%  | 8.7%      |
| 200-999    | 188   | 7.7%   | 4.7% | 11.8% | 7.0%  | 9.1%      |
| 1,000-4,999| 13    | 6.5%   | 5.7% | 11.3% | 3.7%  | 8.1%      |
| 5,000+     | 3     | 9.4%   | 2.6% | 14.7% | 6.1%  | 10.3%     |

Variance tightens with volume. The distribution peaks at 4-6% but has a fat right tail:

```
     0%-2%     ██████████████████  66
     2%-4%     █████████████████████████████  106
     4%-6%     ████████████████████████████████████████  145
     6%-8%     ██████████████████████████████████  124
     8%-10%    ██████████████████████  81
    10%-12%    ████████████████████████  87
    12%-14%    █████████████  49
    14%-16%    ███████████  40
    16%-18%    ██████  22
    18%-20%    █████  19
    20%-22%    ███  13
    22%-24%    █  6
    24%-26%    █  4
    26%-28%      3
    28%-30%      2
    30%-32%      2
    32%-34%      1
    34%-36%      1
    36%-38%      1
    38%-40%      1
    40%-42%      1
    42%-44%      0
    44%-46%      0
    46%-48%      0
    48%-50%      0
    50%+       █  5
```
(pages with 50+ SC clicks, n=779)

## The `(not set)` problem

The GA Google landing pages data has a `(not set)` row with 8,967 sessions — 23% of the 39,592 total. These are Google arrivals where GA couldn't determine the landing page, so they're never subtracted from any specific page's count.

The practical impact is small: those 8,967 sessions are already only the ~10% of Google arrivals that GA can see (the opted-in users). They represent roughly 90,000 real Google arrivals that we can't attribute to specific pages. But those real arrivals *are* captured in the Search Console data — they're just spread across thousands of pages. The `(not set)` only affects the subtraction side, which is small compared to the Search Console addition that dominates the total.

## Per-page consent rate multiplier

A flat multiplier (e.g. 10x) doesn't work well:

- Pages with 0 GA data stay at 0 (10x * 0 = 0)
- Pages with high consent rates (e.g. 50%) get massively over-represented
- The consent rate varies from ~1% to ~53% across publishers

Instead, we use the **per-page consent rate** where we have overlap data.

For pages where we have both GA landing sessions and SC clicks:
1. Calculate the page's consent rate: `max(min(ga_landing / sc_clicks, 1.0), 0.10)`
2. Scale up the non-Google component: `round((ga_views - ga_landing) / consent_rate)`
3. Add SC clicks: `scaled_non_google + sc_clicks`

For pages without overlap data: keep the simple formula `ga_views - ga_landing + sc_clicks`.

Capping at 1.0 handles pages where GA landing sessions exceed SC clicks (due to repeat visits inflating GA) — for those pages, no scaling is applied.

The `0.10` floor handles the opposite tail. A page with only a handful of opted-in landings against many Search Console clicks yields a near-zero rate, and dividing by it inflates views without bound — up to ~230x on the Apr–Aug data, which pushed a low-traffic page to the top of the rankings. Ratios below ~10% are treated as sampling noise and floored at the corpus-wide pooled rate (10.2%). Pages at or above 10% keep their exact rate, so a 50%-consent page still scales 2x.

## Assumptions and limitations

- **The Google consent rate is applied to non-Google traffic.** The scaling assumes direct/referral visitors consent at the same rate as search visitors. That is the opposite of what §Why the variance finds (professional and public audiences behave differently), so the estimate likely **over-inflates high-consent audiences**. It also mixes units: `ga_views - ga_landing` is Views minus Sessions.
- **The 0.10 floor overstates genuinely low-consent pages.** It bounds the error rather than removing it, and is a deliberate simplification — this is an estimate, not a measurement.
- **The tail is noisy.** Individual page rates run from ~1% to ~53%, and before the floor some multipliers reached ~230x. Treat small per-page differences as noise.

## Scripts

All three read the canonical Apr–Aug files (`console-clicks-apr-aug.csv`,
`ga-google-landing-apr-aug.csv`, `ga-views-apr-aug.csv`).

- `scripts/consent_rate.py` — calculates the consent rate analysis (run with `python -m scripts.consent_rate`)
- `scripts/build_db.py` — `load_views_csv()` combines the three sources for dataset views
- `scripts/ingest_collections.py` — `load_collection_views()` does the same for collection views, remapping the pre-rename `government/…` category path to `government-and-parliament/…`

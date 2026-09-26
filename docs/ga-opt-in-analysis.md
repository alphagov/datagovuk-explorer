# GA cookie consent (opt-in) rate analysis

## Background

We combine three data sources to estimate dataset and collection page views:

- **GA page views** — all page views recorded by Google Analytics (cookie opt-in required)
- **GA Google landing pages** — sessions that arrived from Google (cookie opt-in required)
- **Search Console clicks** — clicks from Google search results (no opt-in, counts every click)

The formula: `GA page views - GA Google landing sessions + Search Console clicks`

This replaces GA's count of Google arrivals with Search Console's count, which doesn't depend on cookie consent.

## The consent rate

GA only sees users who accepted the cookie banner. Search Console counts every Google click regardless. For pages that appear in both datasets, the ratio `GA landing sessions / SC clicks` approximates the consent rate.

Analysis period: April – September 2026 (5 months, GA functioning correctly).

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
 10%-12%    ████████████████████████  88
 12%-14%    █████████████  49
 14%-16%    ███████████  40
 16%-18%    ██████  22
 18%-20%    █████  19
 20%+       ██████  40
```
(pages with 50+ SC clicks, n=779)

### Collections vs datasets

| Type        | pages | aggregate | median | p25  | p75   |
|-------------|-------|-----------|--------|------|-------|
| Datasets    | 2,099 | 9.4%      | 8.3%   | 5.3% | 13.5% |
| Collections | 47    | 5.5%      | 12.9%  | 5.3% | 16.2% |

Collections have a higher median consent rate than datasets. This likely reflects repeat visits — collections are curated topic pages (weather, births, house prices) that professionals and researchers bookmark and return to. A user who accepts cookies once generates GA sessions on every return visit, but only one Search Console click per search.

### By publisher organisation

At the org level (orgs with 100+ SC clicks, n=122), the interquartile range is **5.5% – 10.2%** with a median of **8.1%**.

Lowest consent rates:

| Rate | GA | SC | Organisation |
|------|----|----|-------------|
| 1.3% | 18 | 1,382 | Race Equality Unit (REU) |
| 1.8% | 5 | 274 | London Borough of Hackney |
| 1.9% | 2 | 106 | Monmouthshire County Council |
| 2.3% | 3 | 130 | Driver and Vehicle Licensing Agency |
| 2.4% | 4 | 164 | The Disclosure and Barring Service |

Highest consent rates:

| Rate | GA | SC | Organisation |
|------|----|----|-------------|
| 17.0% | 296 | 1,743 | Dept for Business, Innovation, Science and Trade |
| 18.2% | 60 | 329 | Marine Environmental Data & Information Network |
| 22.4% | 49 | 219 | Joint Nature Conservation Committee |
| 23.6% | 107 | 453 | Rochdale Borough Council |
| 53.0% | 218 | 411 | High Speed 2 Limited |

## Why the variance?

The consent rate likely reflects two combined effects:

1. **Cookie acceptance** — whether the visitor clicks accept on the banner
2. **Repeat visits** — a user who accepts cookies once generates GA sessions on every return visit, but only one Search Console click per search

Professional/technical users (HS2, JNCC, Marine Environmental Data) tend to accept cookies and return repeatedly, inflating their consent rate. General public visitors (Race Equality Unit, DVLA) tend to arrive once from Google, probably reject the cookie banner, and never come back.

These two effects can't be separated with the data we have.

## The `(not set)` problem

The GA Google landing pages data has a `(not set)` row with 8,967 sessions — 23% of the 39,592 total. These are Google arrivals where GA couldn't determine the landing page, so they're never subtracted from any specific page's count.

The practical impact is small: those 8,967 sessions are already only the ~10% of Google arrivals that GA can see (the opted-in users). They represent roughly 90,000 real Google arrivals that we can't attribute to specific pages. But those real arrivals *are* captured in the Search Console data — they're just spread across thousands of pages. The `(not set)` only affects the subtraction side, which is small compared to the Search Console addition that dominates the total.

## Per-page consent rate multiplier

A flat multiplier (e.g. 10x) doesn't work well:

- Pages with 0 GA data stay at 0 (10x * 0 = 0)
- Pages with high consent rates (e.g. 50%) get massively over-represented
- The consent rate varies from ~1% to ~53% across publishers

Instead, we use the **exact per-page consent rate** where we have overlap data.

For pages where we have both GA landing sessions and SC clicks:
1. Calculate the page's consent rate: `ga_landing / sc_clicks` (capped at 1.0)
2. Scale up the non-Google component: `round((ga_views - ga_landing) / consent_rate)`
3. Add SC clicks: `scaled_non_google + sc_clicks`

For pages without overlap data: keep the simple formula `ga_views - ga_landing + sc_clicks`.

Capping at 1.0 handles pages where GA landing sessions exceed SC clicks (due to repeat visits inflating GA) — for those pages, no scaling is applied.

## Scripts

- `scripts/consent_rate.py` — calculates the consent rate analysis (run with `python -m scripts.consent_rate`)
- `scripts/build_db.py` — `load_views_csv()` combines the three sources for dataset views
- `scripts/ingest_collections.py` — `load_collection_views()` does the same for collection views

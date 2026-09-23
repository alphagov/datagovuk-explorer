# Estimating GA opt-in rate from Search Console data

Comparing 12 months of Google Search Console clicks against Google Analytics
pageviews on data.gov.uk to estimate what proportion of users consent to GA
tracking.

## Data sources

| Source | Period | Metric | Total |
|---|---|---|---|
| Google Search Console | 12 months (Aug 2025 – Aug 2026) | Clicks | 690,333 |
| Google Analytics (GA4) | 12 months (Aug 2025 – Aug 2026) | Views | 133,836 |

Search Console records every click from Google search results regardless of
cookie consent. GA only records pageviews from users who opt in via the cookie
banner.

## Naive comparison

Dividing GA total views by SC total clicks gives 19.4%, but this overstates the
opt-in rate because GA captures traffic from all channels (direct, referral,
social, etc.) while SC only captures organic search clicks.

## Adjusted estimate using GA channel mix

GA reports that organic search accounts for ~40% of acquisition. This lets us
isolate the organic search channel in both datasets:

| | Value |
|---|---|
| SC clicks (all Google organic users) | 690,333 |
| GA organic search views (~40% of 133,836) | ~53,500 |
| **Estimated opt-in rate** | **~7.8%** |

Google holds ~92% of UK search traffic, so stripping out Bing/DuckDuckGo from
GA's organic number drops the estimate to ~7.1%.

## Why the true rate is likely lower

Organic search users are more likely to be one-and-done visitors — they land on
a result, get what they need, and leave. They're less likely to accept a cookie
banner than someone who navigated directly or plans to browse. This means:

- Organic search is under-represented in GA's channel mix (its true share of
  all traffic is higher than the reported 40%).
- The 7–8% estimate is probably a ceiling, not a midpoint.

This is a circular problem: we need the opt-in rate to correct the channel mix,
but we need the correct channel mix to estimate the opt-in rate.

## Conclusion

The GA opt-in rate on data.gov.uk is estimated at **5–8%**. This is consistent
with consent rates reported on other UK government sites with opt-in cookie
banners.

### Per-page ratios (top pages by SC clicks)

For the highest-traffic dataset pages the GA/SC ratio clusters around 10–20%,
but this is inflated by non-search traffic sources contributing GA views on top
of search landings. The 75th percentile exceeds 100%, confirming that many pages
receive substantial direct/referral traffic in addition to search.

### Limitations

- SC only counts Google search clicks, not all organic search engines.
- GA "views" includes internal navigation (multiple pageviews per session),
  inflating the count relative to SC clicks which are entry-only.
- The 40% organic search share is an approximate figure from GA acquisition
  reports and may vary by time period.
- Pages-per-session may differ across channels, adding noise to the comparison.

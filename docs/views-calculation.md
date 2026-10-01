# Views calculation

Google Analytics undercounts page views because users who decline cookie consent are invisible to it. The formula corrects for this using Search Console clicks, which do not use cookies.

## Three inputs

- **GA page views** (`ga_views`) — raw GA count (includes Google-sourced arrivals, misses consent-decliners)
- **GA Google landing sessions** (`ga_google_landings`) — how many of those GA views came via Google search
- **Search Console clicks** (`console_clicks`) — Google's own count of clicks from search results, unaffected by consent

## Three steps

**Step 1 — isolate non-Google GA views:**

```
non_google = ga_views − ga_google_landings
```

Strips out the Google-sourced slice, since we replace it with the more reliable Search Console number.

**Step 2 — work out the multiplier:**

```
consent_rate = ga_google_landings / console_clicks, or 0.10 whichever is higher
multiplier   = 1 / consent_rate
```

If GA saw 10 Google landings but Search Console recorded 100 clicks, only ~10% of users consented. The floor of 0.10 caps the multiplier at 10× to guard against noise inflating small pages.

**Step 3 — apply it:**

```
corrected = (non_google × multiplier) + console_clicks
```

Scale up the non-Google GA traffic by the consent multiplier, then add Search Console clicks back in for the Google slice.

## Fallback

If either `ga_google_landings` or `console_clicks` is zero (no overlap data for the page), the simpler formula is used:

```
corrected = ga_views − ga_google_landings + console_clicks
```

## Source files

All three inputs come from CSV exports tracked in `data/`:

- `ga-views-apr-aug.csv` — GA page views
- `ga-google-landing-apr-aug.csv` — GA Google landing sessions
- `console-clicks-apr-aug.csv` — Search Console clicks

The constants and implementation are in `scripts/build_db.py` (`load_views_csv`) and `scripts/ingest_collections.py` (`load_collection_views`).

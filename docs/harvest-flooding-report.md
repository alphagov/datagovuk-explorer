# Harvest Flooding Report

**Date:** 2026-09-07  
**Affected organisations:** Sunderland City Council, North Tyneside MBC, Wakefield MDC

---

## Summary

Three councils on the Data Mill North platform are accumulating large numbers of
duplicate dataset records on data.gov.uk. As of 2026-09-07:

| Org | Legitimate pre-2026 records | Flood records (2026–) | Copies per dataset |
|---|---|---|---|
| Sunderland City Council | 82 | 4,501 | 7 |
| North Tyneside MBC | 3 | 2,572 | 4 |
| Wakefield MDC | 16 | 1,929 | 3 |

9,002 flood records represent only 625 unique dataset titles — roughly 7,127
phantom records that should not exist, amounting to ~10.7% of the total 66,554
datasets in the catalogue.

---

## What the evidence shows

### 1. Flood records contain other councils' datasets

The 4,501 Sunderland records created since August 2026 include datasets with
titles like "Leeds crime statistics", "Superfast West Yorkshire broadband
questionnaire", and "Newcastle Libraries buildings". Title-based matching
confirms:

- 1,050 mention Leeds, 189 Newcastle, 91 York, 35 Durham, 14 Bradford
- Only 7 mention Sunderland
- All 9,002 flood records across the three orgs share exactly 625 unique titles

The Data Mill North platform publishes 652 datasets from 69 different
publishers. Sunderland has **1** dataset on the platform, North Tyneside **5**,
Wakefield **22**.

### 2. Each flood harvest run creates exactly 643 new records

Dataset creation timestamps cluster tightly into discrete harvest runs:

| Org | Run dates | Records per run |
|---|---|---|
| Sunderland | Aug 15, 20, 22, 27, 29; Sep 3, 5 | 643 |
| North Tyneside | Aug 15, 22, 29; Sep 5 | 597–643 |
| Wakefield | Aug 19, 26; Sep 2 | 643 |

Each run produces new CKAN dataset records with new UUIDs and new
`metadata_created` timestamps — CKAN is creating, not updating.

### 3. The CKAN-side filter config is the intended filter mechanism

Each harvest source has a `config` field in CKAN containing
`organizations_filter_include`. This is what is supposed to restrict imports to
a specific publisher:

| Org | Config |
|---|---|
| Sunderland | `{"organizations_filter_include": ["Sunderland City Council"]}` |
| North Tyneside | `{"organizations_filter_include": ["North Tyneside Metropolitan Council"]}` |
| Newcastle | `{"organizations_filter_include": ["Newcastle City Council"]}` |
| Wakefield | *(no config)* |

Wakefield has never had a filter configured.

### 4. The filter works for Newcastle, not for Sunderland and North Tyneside

Newcastle City Council has the same `organizations_filter_include` pattern and
its harvest source has been running daily (last run: 2026-09-05, job_count:
2,985). It has 41 datasets in the catalogue — exactly matching the 41 Newcastle
City Council datasets on the Data Mill North platform. No flood.

Sunderland runs daily (job_count: 2,817) and is flooding. North Tyneside runs
weekly (job_count: 2,531) and is flooding.

This is the clearest statement of the problem: **the filter works for Newcastle
but not for Sunderland or North Tyneside**. We do not have enough evidence to
explain why.

### 5. The naming sequence confirms CKAN-wide name collisions

CKAN dataset name slugs are unique across the whole instance. Each time the same
dataset title is imported as a new record, CKAN appends an incrementing counter.
The sequence for "Leeds crime statistics" across all orgs:

```
leeds-crime-statistics    — North Tyneside, Aug 15
leeds-crime-statistics1   — Sunderland,     Aug 15
leeds-crime-statistics2   — Wakefield,      Aug 19
leeds-crime-statistics3   — Sunderland,     Aug 20
...
leeds-crime-statistics13  — Sunderland,     Sep 5
```

The interleaving of three orgs in one counter confirms each run is genuinely
creating new records, not updating existing ones.

### 6. Leeds and other non-flooding DMN sources stopped harvesting

Leeds City Council's DMN harvest source is marked `active=true, DAILY` but its
last recorded harvest was 2021-08-04. Durham stopped in 2024. Their absence from
the flood is because their harvest jobs are not running — not because of any
difference in filter configuration or URL slug format.

### 7. The `?slug=` URL parameter

All DMN harvest source URLs include a `?slug=<org>` parameter (e.g.
`datamillnorth.org/data.json?slug=sunderland-city-council`). Live testing
confirms the parameter has no effect on the response: the same 652 datasets are
returned for any slug value, including nonsense values.

Whether this parameter was ever functional, or was always decorative labelling
in the harvest source URL, is unknown. The `organizations_filter_include` config
is the mechanism that demonstrably does (or does not) restrict what gets
imported.

The same broken-filter behaviour is present on two other platforms:
- `data.london.gov.uk/data.json?slug=gla` — returns all 1,295 datasets regardless of slug
- `open.barnet.gov.uk/data.json?slug=london-borough-of-barnet` — returns all 397

The London Datastore caused a one-time flood of ~717 datasets attributed to the
GLA in June 2026 (datasets from ONS, TfL, Fire Brigade, etc.). Unlike Data Mill
North, it did not repeat — CKAN's update check appears to be working for that
source.

---

## What we don't know

- **Why the filter works for Newcastle but not Sunderland/North Tyneside.** The
  `organizations_filter_include` values are configured correctly in both cases
  and the publisher names match those in the DMN data. We have no access to
  CKAN's internal harvest job logs or the `harvest_object` table.

- **Why CKAN keeps creating rather than updating.** On each run, 643 new records
  are created rather than the existing ones being updated. The CKAN harvest
  framework uses a guid + harvest_source_id lookup to find existing records
  before deciding to create or update. We cannot determine from our data why
  this lookup is failing on each subsequent run for these three orgs.

- **Whether `?slug=` was ever functional.** We have no historical evidence of it
  filtering correctly. It may have always been decorative.

- **What changed in August 2026.** The flood started on 2026-08-15 for all three
  orgs within a few days of each other. Something changed — either on the Data
  Mill North platform or in the data.gov.uk harvest configuration — but we
  cannot identify what from the data we have.

---

## Data quality impact

- 20.7% of flood records have zero resources (identical rate across all three
  orgs, confirming shared origin)
- Sunderland ranks #3 in the catalogue by dataset count, ahead of BGS (4,245)
  and MEDIN (3,998), purely as an artefact of this issue
- The 7,127 phantom records inflate the catalogue count by ~10.7%

# environment.data.gov.uk link error analysis

**3,588 errors out of 8,246 checked links — 43% failure rate**

## Summary by path prefix

| Path | OK | Errors | Verdict |
|---|---|---|---|
| `/ds/` | 0 | 598 | Fully dead |
| `support.*/hc/` | 0 | 61 | Fully dead (DNS does not resolve) |
| `support.*/space/` | 0 | 4 | Fully dead (DNS does not resolve) |
| `/datafiles/` | 0 | 11 | Fully dead |
| `/linked-data/` | 0 | 2 | Fully dead |
| `/catchment-planning/ManagementCatchment/` and `/RiverBasinDistrict/` | 0 | 1,109 | Effectively dead — per-catchment granular endpoints all gone |
| `/api/file/download` | 0 | 1,619 | 244 datasets affected: 404s are mainly CROME 2018–2021 (removed); 403s are ~200 other datasets (gated behind auth) |
| `/DefraDataDownload/?Mode=survey` | 25 | 0 | OK |
| `/DefraDataDownload/?mapService=EA/...&Mode=spatial` | 0 | 25 | Dead — spatial mode removed |
| `/arcgis/rest/services/*/FeatureServer` | 87 | 0 | OK |
| `/arcgis/rest/services/*/MapServer` | 0 | 93 | All timeout — MapServer disabled |
| `/spatialdata/` | 1,108 | 59 | Mostly OK (5% error rate) |

---

## By organisation

The domain is shared across several organisations; the error clusters map almost cleanly onto individual publishers.

| Organisation | OK | Errors | Error % | Primary cause |
|---|---|---|---|---|
| Environment Agency | 2,471 | 1,443 | 37% | Catchment-planning decommission (1,109); /api/file/ 403s (184); support subdomain down (61) |
| Natural England | 1,613 | 193 | 11% | ArcGIS MapServer timeouts (82); /api/file/ 403s (67); /spatialdata/ 404s (24) |
| Rural Payments Agency | 314 | 1,343 | 81% | /api/file/ 404s (1,262) — almost entirely CROME file removals; /api/file/ 403s (74) |
| Marine Management Organisation | 0 | 593 | 100% | All /ds/ 404s — every MMO link on this domain pointed to a /ds/ path, so retiring the catalogue broke all of them |
| Dept for Environment, Food & Rural Affairs | 194 | 8 | 4% | Scattered |
| Forestry Commission | 63 | 5 | 7% | Scattered |

RPA's high rate is inflated by CROME: each annual release has ~300 individual file links, so the removal of four years' worth drives most of their count. MMO's 100% rate reflects the same structural problem: every link they published on this domain pointed at the `/ds/` catalogue, so its retirement broke all of them at once.

---

## Cluster detail

### `/api/file/download` — 1,619 errors (404 + 403)

The `/api/file/download?fileDataSetId=<uuid>&fileName=<file>` endpoint itself still works for many datasets. Errors span 244 distinct datasets; CROME releases dominate the count only because each has hundreds of individual files.

Two distinct failure modes:

- **404** (~1,264): Crop Map of England (CROME) 2018–2021, where each dataset contributes ~300 files. These `fileDataSetId` UUIDs no longer resolve — the data has been removed.
- **403** (~332): ~200 other datasets across a wide range of topics (WFD classification cycles, habitat networks, flood maps, AIMS structures, Great Crested Newt risk zones, Severn Estuary SPA, etc.) — these appear to have been placed behind authentication.
- **Timeouts** (22): a small number on the same path.

### `/catchment-planning/` — 1,109 errors (all 404)

The per-catchment REST API (`/ManagementCatchment/<id>/` and `/RiverBasinDistrict/<id>/`) has been decommissioned. All endpoints returning CSV exports (`?format=csv`) or classification/action/outcome/RNAG data at the individual catchment level return 404.

The top-level and England-aggregate paths still work:

- `/catchment-planning/` → 200
- `/catchment-planning/England/classifications` → 200
- `/catchment-planning/England/rnags.csv` → 200

### `/ds/` — 598 errors (all 404)

Three retired patterns:

- `/ds/catalogue/index.jsp#/catalogue` (296 links) — old JSP catalogue URL
- `/ds/wfs` and `/ds/wms` (99 + 99 links) — OGC WFS/WMS service endpoints
- `/ds/catalogue/#/<uuid>` (remaining ~100) — hash-based catalogue deep links

No `/ds/` URLs return 200.

### ArcGIS — 93 timeouts, 87 OK — clean MapServer vs FeatureServer split

Every `/arcgis/rest/services/*/MapServer` endpoint times out (EA, NE, RPA, SURVEY namespaces). Every `/arcgis/rest/services/*/FeatureServer` endpoint returns 200. MapServer appears to have been disabled on this host; FeatureServer is unaffected.

### `/DefraDataDownload/` — 25 OK, 25 errors — `Mode=survey` vs `Mode=spatial`

`?Mode=survey` works for all 25 links. `?mapService=EA/<service>&Mode=spatial` returns 404 for every spatial-mode URL tested (AIMSBeachStructurePoint, AIMSMajorCivils, SurveyIndexFiles, etc.). The spatial download mode has been removed; the survey download mode is intact.

### `support.environment.data.gov.uk` — 65 errors (DNS not resolved)

The subdomain does not resolve. Affected paths include Zendesk-style help centre URLs (`/hc/en-gb/...`) and Confluence-style documentation (`/space/DPK/...`). The support site has been decommissioned.

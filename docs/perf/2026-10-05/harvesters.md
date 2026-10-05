# /harvesters performance — 2026-10-05

| case | wall | render |
|---|---|---|
| baseline | 132ms | 38ms |
| sort by title asc | 44ms | 25ms |
| filter by active=true | 47ms | 25ms |
| filter by type=ckan | 39ms | 25ms |
| page 2 | 46ms | 25ms |


## baseline
wall=131.5ms  render=38.0ms  (4 queries)

| ms | sql |
|---|---|
| 81.0 | `SELECT h.id, h.title, h.url, h.type, h.active, h.frequency,               h.created, h.last_run,               COALESCE(o.display_name, o.title, o.name) AS org_name,               h.dataset_count        FROM harvest_sources h        LEFT JOIN organisations o ON o.slug = h.org_slug        ORDER BY LO...` |
| 5.0 | `SELECT COUNT(*) AS n FROM datasets WHERE harvested = 1` |
| 2.0 | `SELECT h.id, h.title, h.url, h.type, h.active, h.frequency, h.created,       h.last_run,       COALESCE(o.display_name, o.title, o.name) AS org_name,       h.dataset_count FROM harvest_sources h LEFT JOIN organisations o ON o.slug = h.org_slug ORDER BY COALESCE(h.dataset_count, 0) DESC, LOWER(h.titl...` |
| 1.0 | `SELECT COUNT(*) AS n FROM (SELECT h.id, h.title, h.url, h.type, h.active, h.frequency, h.created,       h.last_run,       COALESCE(o.display_name, o.title, o.name) AS org_name,       h.dataset_count FROM harvest_sources h LEFT JOIN organisations o ON o.slug = h.org_slug) s` |

## sort by title asc
wall=43.5ms  render=25.3ms  (4 queries)

| ms | sql |
|---|---|
| 7.0 | `SELECT h.id, h.title, h.url, h.type, h.active, h.frequency,               h.created, h.last_run,               COALESCE(o.display_name, o.title, o.name) AS org_name,               h.dataset_count        FROM harvest_sources h        LEFT JOIN organisations o ON o.slug = h.org_slug        ORDER BY LO...` |
| 6.0 | `SELECT COUNT(*) AS n FROM datasets WHERE harvested = 1` |
| 4.0 | `SELECT h.id, h.title, h.url, h.type, h.active, h.frequency, h.created,       h.last_run,       COALESCE(o.display_name, o.title, o.name) AS org_name,       h.dataset_count FROM harvest_sources h LEFT JOIN organisations o ON o.slug = h.org_slug ORDER BY LOWER(COALESCE(h.title, '')) ASC, LOWER(h.title...` |
| 1.0 | `SELECT COUNT(*) AS n FROM (SELECT h.id, h.title, h.url, h.type, h.active, h.frequency, h.created,       h.last_run,       COALESCE(o.display_name, o.title, o.name) AS org_name,       h.dataset_count FROM harvest_sources h LEFT JOIN organisations o ON o.slug = h.org_slug) s` |

## filter by active=true
wall=47.3ms  render=25.2ms  (4 queries)

| ms | sql |
|---|---|
| 9.0 | `SELECT COUNT(*) AS n FROM datasets WHERE harvested = 1` |
| 8.0 | `SELECT h.id, h.title, h.url, h.type, h.active, h.frequency,               h.created, h.last_run,               COALESCE(o.display_name, o.title, o.name) AS org_name,               h.dataset_count        FROM harvest_sources h        LEFT JOIN organisations o ON o.slug = h.org_slug        ORDER BY LO...` |
| 4.0 | `SELECT h.id, h.title, h.url, h.type, h.active, h.frequency, h.created,       h.last_run,       COALESCE(o.display_name, o.title, o.name) AS org_name,       h.dataset_count FROM harvest_sources h LEFT JOIN organisations o ON o.slug = h.org_slug WHERE h.active = %s ORDER BY COALESCE(h.dataset_count, 0...` |
| 1.0 | `SELECT COUNT(*) AS n FROM (SELECT h.id, h.title, h.url, h.type, h.active, h.frequency, h.created,       h.last_run,       COALESCE(o.display_name, o.title, o.name) AS org_name,       h.dataset_count FROM harvest_sources h LEFT JOIN organisations o ON o.slug = h.org_slug WHERE h.active = %s) s` |

## filter by type=ckan
wall=39.3ms  render=24.8ms  (4 queries)

| ms | sql |
|---|---|
| 6.0 | `SELECT h.id, h.title, h.url, h.type, h.active, h.frequency,               h.created, h.last_run,               COALESCE(o.display_name, o.title, o.name) AS org_name,               h.dataset_count        FROM harvest_sources h        LEFT JOIN organisations o ON o.slug = h.org_slug        ORDER BY LO...` |
| 5.0 | `SELECT COUNT(*) AS n FROM datasets WHERE harvested = 1` |
| 2.0 | `SELECT h.id, h.title, h.url, h.type, h.active, h.frequency, h.created,       h.last_run,       COALESCE(o.display_name, o.title, o.name) AS org_name,       h.dataset_count FROM harvest_sources h LEFT JOIN organisations o ON o.slug = h.org_slug WHERE h.type = %s ORDER BY COALESCE(h.dataset_count, 0) ...` |
| 1.0 | `SELECT COUNT(*) AS n FROM (SELECT h.id, h.title, h.url, h.type, h.active, h.frequency, h.created,       h.last_run,       COALESCE(o.display_name, o.title, o.name) AS org_name,       h.dataset_count FROM harvest_sources h LEFT JOIN organisations o ON o.slug = h.org_slug WHERE h.type = %s) s` |

## page 2
wall=45.9ms  render=25.4ms  (4 queries)

| ms | sql |
|---|---|
| 7.0 | `SELECT COUNT(*) AS n FROM datasets WHERE harvested = 1` |
| 6.0 | `SELECT h.id, h.title, h.url, h.type, h.active, h.frequency,               h.created, h.last_run,               COALESCE(o.display_name, o.title, o.name) AS org_name,               h.dataset_count        FROM harvest_sources h        LEFT JOIN organisations o ON o.slug = h.org_slug        ORDER BY LO...` |
| 5.0 | `SELECT h.id, h.title, h.url, h.type, h.active, h.frequency, h.created,       h.last_run,       COALESCE(o.display_name, o.title, o.name) AS org_name,       h.dataset_count FROM harvest_sources h LEFT JOIN organisations o ON o.slug = h.org_slug ORDER BY COALESCE(h.dataset_count, 0) DESC, LOWER(h.titl...` |
| 1.0 | `SELECT COUNT(*) AS n FROM (SELECT h.id, h.title, h.url, h.type, h.active, h.frequency, h.created,       h.last_run,       COALESCE(o.display_name, o.title, o.name) AS org_name,       h.dataset_count FROM harvest_sources h LEFT JOIN organisations o ON o.slug = h.org_slug) s` |

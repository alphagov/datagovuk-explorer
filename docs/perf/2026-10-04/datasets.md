# /datasets performance — 2026-10-04

| case | wall | sql | render |
|---|---|---|---|
| baseline | 297ms | 247ms | 51ms |
| sort by resources desc | 173ms | 139ms | 34ms |
| filter by source=harvested | 307ms | 273ms | 35ms |
| filter by theme=none | 255ms | 220ms | 35ms |
| page 2 | 133ms | 101ms | 32ms |


## baseline
wall=297.4ms  render=50.8ms  (15 queries, parallel)

| ms | thread | sql |
|---|---|---|
| 89.0 | main | `SELECT DISTINCT org_slug FROM datasets` |
| 69.0 | main | `SELECT d.org_slug AS value,       COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug) AS name, COUNT(*) AS count FROM datasets d GROUP BY d.org_slug ORDER BY count DESC, LOWER(COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug))` |
| 69.0 | main | `SELECT CASE WHEN COALESCE(d.resource_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(d.resource_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(d.resource_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(d.resource_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(d.resource_count...` |
| 66.0 | main | `SELECT COUNT(*) FILTER (WHERE harvested = 1) AS harvested,       COUNT(*) FILTER (WHERE harvested = 0) AS manual FROM datasets d` |
| 66.0 | main | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count FROM datasets d GROUP BY COALESCE(theme_primary, '__none__')` |
| 60.0 | main | `SELECT substr(metadata_created, 1, 4) AS created_year, COUNT(*) AS count FROM datasets d WHERE d.metadata_created IS NOT NULL GROUP BY substr(metadata_created, 1, 4)` |
| 51.0 | main | `SELECT dy.year, COUNT(*) AS count FROM dataset_years dy JOIN datasets d ON d.id = dy.dataset_id AND dy.year <= 2026 GROUP BY dy.year` |
| 43.0 | main | `SELECT  COUNT(*) FILTER (WHERE tp.dataset_id IS NULL) AS none,  COUNT(*) FILTER (WHERE tp.has_pre1900) AS pre1900,  COUNT(*) FILTER (WHERE tp.has_post) AS post FROM datasets d LEFT JOIN (   SELECT dataset_id,    BOOL_OR(COALESCE(from_year, to_year) < 1900) AS has_pre1900,    BOOL_OR(COALESCE(to_year...` |
| 31.0 | main | `SELECT da.api_category AS api, COUNT(*) AS count FROM datasets d JOIN dataset_api da ON da.dataset_id = d.id GROUP BY da.api_category` |
| 13.0 | main | `SELECT DISTINCT year FROM dataset_years WHERE year <= 2026 ORDER BY year DESC` |
| 11.0 | main | `SELECT substr(metadata_created, 1, 4) AS year, COUNT(*) AS count        FROM datasets WHERE metadata_created IS NOT NULL        GROUP BY substr(metadata_created, 1, 4)` |
| 7.0 | main | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count        FROM datasets GROUP BY COALESCE(theme_primary, '__none__')` |
| 2.0 | main | `SELECT COUNT(*) AS n FROM datasets d` |
| 2.0 | main | `SELECT COUNT(*) AS n FROM datasets` |
| 1.0 | main | `SELECT d.ckan_id, d.title, d.name, d.org_slug,  d.org_display_name AS organisation,  d.metadata_created, d.metadata_modified, d.resource_count,  d.theme_primary, d.harvested, d.harvest_source_title, d.views FROM datasets d ORDER BY d.views DESC, d.id LIMIT %s OFFSET %s` |

## sort by resources desc
wall=173.3ms  render=34.5ms  (13 queries, parallel)

| ms | thread | sql |
|---|---|---|
| 51.0 | main | `SELECT substr(metadata_created, 1, 4) AS created_year, COUNT(*) AS count FROM datasets d WHERE d.metadata_created IS NOT NULL GROUP BY substr(metadata_created, 1, 4)` |
| 49.0 | main | `SELECT d.org_slug AS value,       COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug) AS name, COUNT(*) AS count FROM datasets d GROUP BY d.org_slug ORDER BY count DESC, LOWER(COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug))` |
| 49.0 | main | `SELECT CASE WHEN COALESCE(d.resource_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(d.resource_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(d.resource_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(d.resource_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(d.resource_count...` |
| 47.0 | main | `SELECT COUNT(*) FILTER (WHERE harvested = 1) AS harvested,       COUNT(*) FILTER (WHERE harvested = 0) AS manual FROM datasets d` |
| 43.0 | main | `SELECT dy.year, COUNT(*) AS count FROM dataset_years dy JOIN datasets d ON d.id = dy.dataset_id AND dy.year <= 2026 GROUP BY dy.year` |
| 37.0 | main | `SELECT  COUNT(*) FILTER (WHERE tp.dataset_id IS NULL) AS none,  COUNT(*) FILTER (WHERE tp.has_pre1900) AS pre1900,  COUNT(*) FILTER (WHERE tp.has_post) AS post FROM datasets d LEFT JOIN (   SELECT dataset_id,    BOOL_OR(COALESCE(from_year, to_year) < 1900) AS has_pre1900,    BOOL_OR(COALESCE(to_year...` |
| 36.0 | main | `SELECT d.ckan_id, d.title, d.name, d.org_slug,  d.org_display_name AS organisation,  d.metadata_created, d.metadata_modified, d.resource_count,  d.theme_primary, d.harvested, d.harvest_source_title, d.views FROM datasets d ORDER BY COALESCE(d.resource_count, 0) DESC, d.id LIMIT %s OFFSET %s` |
| 34.0 | main | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count FROM datasets d GROUP BY COALESCE(theme_primary, '__none__')` |
| 26.0 | main | `SELECT da.api_category AS api, COUNT(*) AS count FROM datasets d JOIN dataset_api da ON da.dataset_id = d.id GROUP BY da.api_category` |
| 10.0 | main | `SELECT DISTINCT year FROM dataset_years WHERE year <= 2026 ORDER BY year DESC` |
| 4.0 | main | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count        FROM datasets GROUP BY COALESCE(theme_primary, '__none__')` |
| 2.0 | main | `SELECT COUNT(*) AS n FROM datasets d` |
| 1.0 | main | `SELECT COUNT(*) AS n FROM datasets` |

## filter by source=harvested
wall=307.3ms  render=34.7ms  (13 queries, parallel)

| ms | thread | sql |
|---|---|---|
| 156.0 | main | `SELECT substr(metadata_created, 1, 4) AS created_year, COUNT(*) AS count FROM datasets d WHERE d.harvested = 1 AND d.metadata_created IS NOT NULL GROUP BY substr(metadata_created, 1, 4)` |
| 152.0 | main | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count FROM datasets d WHERE d.harvested = 1 GROUP BY COALESCE(theme_primary, '__none__')` |
| 149.0 | main | `SELECT d.org_slug AS value,       COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug) AS name, COUNT(*) AS count FROM datasets d WHERE d.harvested = 1 GROUP BY d.org_slug ORDER BY count DESC, LOWER(COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug))` |
| 133.0 | main | `SELECT  COUNT(*) FILTER (WHERE tp.dataset_id IS NULL) AS none,  COUNT(*) FILTER (WHERE tp.has_pre1900) AS pre1900,  COUNT(*) FILTER (WHERE tp.has_post) AS post FROM datasets d LEFT JOIN (   SELECT dataset_id,    BOOL_OR(COALESCE(from_year, to_year) < 1900) AS has_pre1900,    BOOL_OR(COALESCE(to_year...` |
| 124.0 | main | `SELECT da.api_category AS api, COUNT(*) AS count FROM datasets d JOIN dataset_api da ON da.dataset_id = d.id WHERE d.harvested = 1 GROUP BY da.api_category` |
| 90.0 | main | `SELECT CASE WHEN COALESCE(d.resource_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(d.resource_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(d.resource_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(d.resource_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(d.resource_count...` |
| 86.0 | main | `SELECT dy.year, COUNT(*) AS count FROM dataset_years dy JOIN datasets d ON d.id = dy.dataset_id AND dy.year <= 2026 WHERE d.harvested = 1 GROUP BY dy.year` |
| 43.0 | main | `SELECT COUNT(*) FILTER (WHERE harvested = 1) AS harvested,       COUNT(*) FILTER (WHERE harvested = 0) AS manual FROM datasets d` |
| 9.0 | main | `SELECT DISTINCT year FROM dataset_years WHERE year <= 2026 ORDER BY year DESC` |
| 4.0 | main | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count        FROM datasets GROUP BY COALESCE(theme_primary, '__none__')` |
| 2.0 | main | `SELECT COUNT(*) AS n FROM datasets` |
| 1.0 | main | `SELECT COUNT(*) AS n FROM datasets d WHERE d.harvested = 1` |
| 1.0 | main | `SELECT d.ckan_id, d.title, d.name, d.org_slug,  d.org_display_name AS organisation,  d.metadata_created, d.metadata_modified, d.resource_count,  d.theme_primary, d.harvested, d.harvest_source_title, d.views FROM datasets d WHERE d.harvested = 1 ORDER BY d.views DESC, d.id LIMIT %s OFFSET %s` |

## filter by theme=none
wall=255.4ms  render=35.3ms  (13 queries, parallel)

| ms | thread | sql |
|---|---|---|
| 142.0 | main | `SELECT COUNT(*) FILTER (WHERE harvested = 1) AS harvested,       COUNT(*) FILTER (WHERE harvested = 0) AS manual FROM datasets d WHERE d.theme_primary IS NULL` |
| 138.0 | main | `SELECT substr(metadata_created, 1, 4) AS created_year, COUNT(*) AS count FROM datasets d WHERE d.theme_primary IS NULL AND d.metadata_created IS NOT NULL GROUP BY substr(metadata_created, 1, 4)` |
| 128.0 | main | `SELECT  COUNT(*) FILTER (WHERE tp.dataset_id IS NULL) AS none,  COUNT(*) FILTER (WHERE tp.has_pre1900) AS pre1900,  COUNT(*) FILTER (WHERE tp.has_post) AS post FROM datasets d LEFT JOIN (   SELECT dataset_id,    BOOL_OR(COALESCE(from_year, to_year) < 1900) AS has_pre1900,    BOOL_OR(COALESCE(to_year...` |
| 115.0 | main | `SELECT da.api_category AS api, COUNT(*) AS count FROM datasets d JOIN dataset_api da ON da.dataset_id = d.id WHERE d.theme_primary IS NULL GROUP BY da.api_category` |
| 86.0 | main | `SELECT CASE WHEN COALESCE(d.resource_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(d.resource_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(d.resource_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(d.resource_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(d.resource_count...` |
| 83.0 | main | `SELECT dy.year, COUNT(*) AS count FROM dataset_years dy JOIN datasets d ON d.id = dy.dataset_id AND dy.year <= 2026 WHERE d.theme_primary IS NULL GROUP BY dy.year` |
| 70.0 | main | `SELECT d.org_slug AS value,       COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug) AS name, COUNT(*) AS count FROM datasets d WHERE d.theme_primary IS NULL GROUP BY d.org_slug ORDER BY count DESC, LOWER(COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug))` |
| 32.0 | main | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count FROM datasets d GROUP BY COALESCE(theme_primary, '__none__')` |
| 9.0 | main | `SELECT DISTINCT year FROM dataset_years WHERE year <= 2026 ORDER BY year DESC` |
| 4.0 | main | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count        FROM datasets GROUP BY COALESCE(theme_primary, '__none__')` |
| 2.0 | main | `SELECT COUNT(*) AS n FROM datasets` |
| 1.0 | main | `SELECT COUNT(*) AS n FROM datasets d WHERE d.theme_primary IS NULL` |
| 1.0 | main | `SELECT d.ckan_id, d.title, d.name, d.org_slug,  d.org_display_name AS organisation,  d.metadata_created, d.metadata_modified, d.resource_count,  d.theme_primary, d.harvested, d.harvest_source_title, d.views FROM datasets d WHERE d.theme_primary IS NULL ORDER BY d.views DESC, d.id LIMIT %s OFFSET %s` |

## page 2
wall=133.2ms  render=32.4ms  (13 queries, parallel)

| ms | thread | sql |
|---|---|---|
| 45.0 | main | `SELECT d.org_slug AS value,       COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug) AS name, COUNT(*) AS count FROM datasets d GROUP BY d.org_slug ORDER BY count DESC, LOWER(COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug))` |
| 45.0 | main | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count FROM datasets d GROUP BY COALESCE(theme_primary, '__none__')` |
| 45.0 | main | `SELECT substr(metadata_created, 1, 4) AS created_year, COUNT(*) AS count FROM datasets d WHERE d.metadata_created IS NOT NULL GROUP BY substr(metadata_created, 1, 4)` |
| 44.0 | main | `SELECT dy.year, COUNT(*) AS count FROM dataset_years dy JOIN datasets d ON d.id = dy.dataset_id AND dy.year <= 2026 GROUP BY dy.year` |
| 40.0 | main | `SELECT COUNT(*) FILTER (WHERE harvested = 1) AS harvested,       COUNT(*) FILTER (WHERE harvested = 0) AS manual FROM datasets d` |
| 39.0 | main | `SELECT  COUNT(*) FILTER (WHERE tp.dataset_id IS NULL) AS none,  COUNT(*) FILTER (WHERE tp.has_pre1900) AS pre1900,  COUNT(*) FILTER (WHERE tp.has_post) AS post FROM datasets d LEFT JOIN (   SELECT dataset_id,    BOOL_OR(COALESCE(from_year, to_year) < 1900) AS has_pre1900,    BOOL_OR(COALESCE(to_year...` |
| 38.0 | main | `SELECT CASE WHEN COALESCE(d.resource_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(d.resource_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(d.resource_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(d.resource_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(d.resource_count...` |
| 27.0 | main | `SELECT da.api_category AS api, COUNT(*) AS count FROM datasets d JOIN dataset_api da ON da.dataset_id = d.id GROUP BY da.api_category` |
| 9.0 | main | `SELECT DISTINCT year FROM dataset_years WHERE year <= 2026 ORDER BY year DESC` |
| 4.0 | main | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count        FROM datasets GROUP BY COALESCE(theme_primary, '__none__')` |
| 1.0 | main | `SELECT COUNT(*) AS n FROM datasets d` |
| 1.0 | main | `SELECT d.ckan_id, d.title, d.name, d.org_slug,  d.org_display_name AS organisation,  d.metadata_created, d.metadata_modified, d.resource_count,  d.theme_primary, d.harvested, d.harvest_source_title, d.views FROM datasets d ORDER BY d.views DESC, d.id LIMIT %s OFFSET %s` |
| 1.0 | main | `SELECT COUNT(*) AS n FROM datasets` |

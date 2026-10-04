# /datasets performance — 2026-10-04

| case | wall | render |
|---|---|---|
| baseline | 351ms | 93ms |
| sort by resources desc | 197ms | 43ms |
| filter by source=harvested | 338ms | 35ms |
| filter by theme=none | 268ms | 36ms |
| page 2 | 133ms | 32ms |


## baseline
wall=351.5ms  render=92.6ms  (15 queries, parallel)

| ms | sql |
|---|---|
| 90.0 | `SELECT DISTINCT org_slug FROM datasets` |
| 74.0 | `SELECT d.org_slug AS value,       COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug) AS name, COUNT(*) AS count FROM datasets d GROUP BY d.org_slug ORDER BY count DESC, LOWER(COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug))` |
| 70.0 | `SELECT substr(metadata_created, 1, 4) AS created_year, COUNT(*) AS count FROM datasets d WHERE d.metadata_created IS NOT NULL GROUP BY substr(metadata_created, 1, 4)` |
| 66.0 | `SELECT CASE WHEN COALESCE(d.resource_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(d.resource_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(d.resource_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(d.resource_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(d.resource_count...` |
| 65.0 | `SELECT COUNT(*) FILTER (WHERE harvested = 1) AS harvested,       COUNT(*) FILTER (WHERE harvested = 0) AS manual FROM datasets d` |
| 55.0 | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count FROM datasets d GROUP BY COALESCE(theme_primary, '__none__')` |
| 52.0 | `SELECT dy.year, COUNT(*) AS count FROM dataset_years dy JOIN datasets d ON d.id = dy.dataset_id AND dy.year <= 2026 GROUP BY dy.year` |
| 45.0 | `SELECT  COUNT(*) FILTER (WHERE tp.dataset_id IS NULL) AS none,  COUNT(*) FILTER (WHERE tp.has_pre1900) AS pre1900,  COUNT(*) FILTER (WHERE tp.has_post) AS post FROM datasets d LEFT JOIN (   SELECT dataset_id,    BOOL_OR(COALESCE(from_year, to_year) < 1900) AS has_pre1900,    BOOL_OR(COALESCE(to_year...` |
| 38.0 | `SELECT da.api_category AS api, COUNT(*) AS count FROM datasets d JOIN dataset_api da ON da.dataset_id = d.id GROUP BY da.api_category` |
| 20.0 | `SELECT DISTINCT year FROM dataset_years WHERE year <= 2026 ORDER BY year DESC` |
| 15.0 | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count        FROM datasets GROUP BY COALESCE(theme_primary, '__none__')` |
| 11.0 | `SELECT substr(metadata_created, 1, 4) AS year, COUNT(*) AS count        FROM datasets WHERE metadata_created IS NOT NULL        GROUP BY substr(metadata_created, 1, 4)` |
| 2.0 | `SELECT COUNT(*) AS n FROM datasets d` |
| 2.0 | `SELECT COUNT(*) AS n FROM datasets` |
| 1.0 | `SELECT d.ckan_id, d.title, d.name, d.org_slug,  d.org_display_name AS organisation,  d.metadata_created, d.metadata_modified, d.resource_count,  d.theme_primary, d.harvested, d.harvest_source_title, d.views FROM datasets d ORDER BY d.views DESC, d.id LIMIT %s OFFSET %s` |

## sort by resources desc
wall=196.8ms  render=42.6ms  (13 queries, parallel)

| ms | sql |
|---|---|
| 72.0 | `SELECT d.org_slug AS value,       COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug) AS name, COUNT(*) AS count FROM datasets d GROUP BY d.org_slug ORDER BY count DESC, LOWER(COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug))` |
| 70.0 | `SELECT CASE WHEN COALESCE(d.resource_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(d.resource_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(d.resource_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(d.resource_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(d.resource_count...` |
| 62.0 | `SELECT substr(metadata_created, 1, 4) AS created_year, COUNT(*) AS count FROM datasets d WHERE d.metadata_created IS NOT NULL GROUP BY substr(metadata_created, 1, 4)` |
| 51.0 | `SELECT COUNT(*) FILTER (WHERE harvested = 1) AS harvested,       COUNT(*) FILTER (WHERE harvested = 0) AS manual FROM datasets d` |
| 47.0 | `SELECT dy.year, COUNT(*) AS count FROM dataset_years dy JOIN datasets d ON d.id = dy.dataset_id AND dy.year <= 2026 GROUP BY dy.year` |
| 46.0 | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count FROM datasets d GROUP BY COALESCE(theme_primary, '__none__')` |
| 40.0 | `SELECT d.ckan_id, d.title, d.name, d.org_slug,  d.org_display_name AS organisation,  d.metadata_created, d.metadata_modified, d.resource_count,  d.theme_primary, d.harvested, d.harvest_source_title, d.views FROM datasets d ORDER BY COALESCE(d.resource_count, 0) DESC, d.id LIMIT %s OFFSET %s` |
| 36.0 | `SELECT  COUNT(*) FILTER (WHERE tp.dataset_id IS NULL) AS none,  COUNT(*) FILTER (WHERE tp.has_pre1900) AS pre1900,  COUNT(*) FILTER (WHERE tp.has_post) AS post FROM datasets d LEFT JOIN (   SELECT dataset_id,    BOOL_OR(COALESCE(from_year, to_year) < 1900) AS has_pre1900,    BOOL_OR(COALESCE(to_year...` |
| 27.0 | `SELECT da.api_category AS api, COUNT(*) AS count FROM datasets d JOIN dataset_api da ON da.dataset_id = d.id GROUP BY da.api_category` |
| 10.0 | `SELECT DISTINCT year FROM dataset_years WHERE year <= 2026 ORDER BY year DESC` |
| 4.0 | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count        FROM datasets GROUP BY COALESCE(theme_primary, '__none__')` |
| 2.0 | `SELECT COUNT(*) AS n FROM datasets d` |
| 2.0 | `SELECT COUNT(*) AS n FROM datasets` |

## filter by source=harvested
wall=338.0ms  render=35.5ms  (13 queries, parallel)

| ms | sql |
|---|---|
| 201.0 | `SELECT d.org_slug AS value,       COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug) AS name, COUNT(*) AS count FROM datasets d WHERE d.harvested = 1 GROUP BY d.org_slug ORDER BY count DESC, LOWER(COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug))` |
| 199.0 | `SELECT substr(metadata_created, 1, 4) AS created_year, COUNT(*) AS count FROM datasets d WHERE d.harvested = 1 AND d.metadata_created IS NOT NULL GROUP BY substr(metadata_created, 1, 4)` |
| 191.0 | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count FROM datasets d WHERE d.harvested = 1 GROUP BY COALESCE(theme_primary, '__none__')` |
| 173.0 | `SELECT  COUNT(*) FILTER (WHERE tp.dataset_id IS NULL) AS none,  COUNT(*) FILTER (WHERE tp.has_pre1900) AS pre1900,  COUNT(*) FILTER (WHERE tp.has_post) AS post FROM datasets d LEFT JOIN (   SELECT dataset_id,    BOOL_OR(COALESCE(from_year, to_year) < 1900) AS has_pre1900,    BOOL_OR(COALESCE(to_year...` |
| 160.0 | `SELECT da.api_category AS api, COUNT(*) AS count FROM datasets d JOIN dataset_api da ON da.dataset_id = d.id WHERE d.harvested = 1 GROUP BY da.api_category` |
| 98.0 | `SELECT CASE WHEN COALESCE(d.resource_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(d.resource_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(d.resource_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(d.resource_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(d.resource_count...` |
| 93.0 | `SELECT dy.year, COUNT(*) AS count FROM dataset_years dy JOIN datasets d ON d.id = dy.dataset_id AND dy.year <= 2026 WHERE d.harvested = 1 GROUP BY dy.year` |
| 30.0 | `SELECT COUNT(*) FILTER (WHERE harvested = 1) AS harvested,       COUNT(*) FILTER (WHERE harvested = 0) AS manual FROM datasets d` |
| 9.0 | `SELECT DISTINCT year FROM dataset_years WHERE year <= 2026 ORDER BY year DESC` |
| 4.0 | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count        FROM datasets GROUP BY COALESCE(theme_primary, '__none__')` |
| 2.0 | `SELECT COUNT(*) AS n FROM datasets` |
| 1.0 | `SELECT COUNT(*) AS n FROM datasets d WHERE d.harvested = 1` |
| 1.0 | `SELECT d.ckan_id, d.title, d.name, d.org_slug,  d.org_display_name AS organisation,  d.metadata_created, d.metadata_modified, d.resource_count,  d.theme_primary, d.harvested, d.harvest_source_title, d.views FROM datasets d WHERE d.harvested = 1 ORDER BY d.views DESC, d.id LIMIT %s OFFSET %s` |

## filter by theme=none
wall=268.2ms  render=35.6ms  (13 queries, parallel)

| ms | sql |
|---|---|
| 131.0 | `SELECT  COUNT(*) FILTER (WHERE tp.dataset_id IS NULL) AS none,  COUNT(*) FILTER (WHERE tp.has_pre1900) AS pre1900,  COUNT(*) FILTER (WHERE tp.has_post) AS post FROM datasets d LEFT JOIN (   SELECT dataset_id,    BOOL_OR(COALESCE(from_year, to_year) < 1900) AS has_pre1900,    BOOL_OR(COALESCE(to_year...` |
| 125.0 | `SELECT substr(metadata_created, 1, 4) AS created_year, COUNT(*) AS count FROM datasets d WHERE d.theme_primary IS NULL AND d.metadata_created IS NOT NULL GROUP BY substr(metadata_created, 1, 4)` |
| 124.0 | `SELECT da.api_category AS api, COUNT(*) AS count FROM datasets d JOIN dataset_api da ON da.dataset_id = d.id WHERE d.theme_primary IS NULL GROUP BY da.api_category` |
| 121.0 | `SELECT COUNT(*) FILTER (WHERE harvested = 1) AS harvested,       COUNT(*) FILTER (WHERE harvested = 0) AS manual FROM datasets d WHERE d.theme_primary IS NULL` |
| 90.0 | `SELECT CASE WHEN COALESCE(d.resource_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(d.resource_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(d.resource_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(d.resource_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(d.resource_count...` |
| 85.0 | `SELECT dy.year, COUNT(*) AS count FROM dataset_years dy JOIN datasets d ON d.id = dy.dataset_id AND dy.year <= 2026 WHERE d.theme_primary IS NULL GROUP BY dy.year` |
| 61.0 | `SELECT d.org_slug AS value,       COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug) AS name, COUNT(*) AS count FROM datasets d WHERE d.theme_primary IS NULL GROUP BY d.org_slug ORDER BY count DESC, LOWER(COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug))` |
| 36.0 | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count FROM datasets d GROUP BY COALESCE(theme_primary, '__none__')` |
| 9.0 | `SELECT DISTINCT year FROM dataset_years WHERE year <= 2026 ORDER BY year DESC` |
| 4.0 | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count        FROM datasets GROUP BY COALESCE(theme_primary, '__none__')` |
| 2.0 | `SELECT COUNT(*) AS n FROM datasets` |
| 1.0 | `SELECT COUNT(*) AS n FROM datasets d WHERE d.theme_primary IS NULL` |
| 1.0 | `SELECT d.ckan_id, d.title, d.name, d.org_slug,  d.org_display_name AS organisation,  d.metadata_created, d.metadata_modified, d.resource_count,  d.theme_primary, d.harvested, d.harvest_source_title, d.views FROM datasets d WHERE d.theme_primary IS NULL ORDER BY d.views DESC, d.id LIMIT %s OFFSET %s` |

## page 2
wall=133.2ms  render=32.5ms  (13 queries, parallel)

| ms | sql |
|---|---|
| 60.0 | `SELECT d.org_slug AS value,       COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug) AS name, COUNT(*) AS count FROM datasets d GROUP BY d.org_slug ORDER BY count DESC, LOWER(COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug))` |
| 50.0 | `SELECT substr(metadata_created, 1, 4) AS created_year, COUNT(*) AS count FROM datasets d WHERE d.metadata_created IS NOT NULL GROUP BY substr(metadata_created, 1, 4)` |
| 44.0 | `SELECT dy.year, COUNT(*) AS count FROM dataset_years dy JOIN datasets d ON d.id = dy.dataset_id AND dy.year <= 2026 GROUP BY dy.year` |
| 43.0 | `SELECT  COUNT(*) FILTER (WHERE tp.dataset_id IS NULL) AS none,  COUNT(*) FILTER (WHERE tp.has_pre1900) AS pre1900,  COUNT(*) FILTER (WHERE tp.has_post) AS post FROM datasets d LEFT JOIN (   SELECT dataset_id,    BOOL_OR(COALESCE(from_year, to_year) < 1900) AS has_pre1900,    BOOL_OR(COALESCE(to_year...` |
| 40.0 | `SELECT CASE WHEN COALESCE(d.resource_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(d.resource_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(d.resource_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(d.resource_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(d.resource_count...` |
| 40.0 | `SELECT COUNT(*) FILTER (WHERE harvested = 1) AS harvested,       COUNT(*) FILTER (WHERE harvested = 0) AS manual FROM datasets d` |
| 31.0 | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count FROM datasets d GROUP BY COALESCE(theme_primary, '__none__')` |
| 29.0 | `SELECT da.api_category AS api, COUNT(*) AS count FROM datasets d JOIN dataset_api da ON da.dataset_id = d.id GROUP BY da.api_category` |
| 9.0 | `SELECT DISTINCT year FROM dataset_years WHERE year <= 2026 ORDER BY year DESC` |
| 4.0 | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count        FROM datasets GROUP BY COALESCE(theme_primary, '__none__')` |
| 1.0 | `SELECT COUNT(*) AS n FROM datasets d` |
| 1.0 | `SELECT d.ckan_id, d.title, d.name, d.org_slug,  d.org_display_name AS organisation,  d.metadata_created, d.metadata_modified, d.resource_count,  d.theme_primary, d.harvested, d.harvest_source_title, d.views FROM datasets d ORDER BY d.views DESC, d.id LIMIT %s OFFSET %s` |
| 1.0 | `SELECT COUNT(*) AS n FROM datasets` |

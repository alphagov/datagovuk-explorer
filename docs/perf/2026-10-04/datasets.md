# /datasets performance — 2026-10-04

| case | wall | render |
|---|---|---|
| baseline | 187ms | 43ms |
| sort by resources desc | 167ms | 35ms |
| filter by source=harvested | 337ms | 36ms |
| filter by theme=none | 270ms | 35ms |
| page 2 | 134ms | 33ms |


## baseline
wall=187.1ms  render=43.3ms  (13 queries, parallel)

| ms | sql |
|---|---|
| 89.0 | `SELECT d.org_slug AS value,       COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug) AS name, COUNT(*) AS count FROM datasets d GROUP BY d.org_slug ORDER BY count DESC, LOWER(COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug))` |
| 75.0 | `SELECT CASE WHEN COALESCE(d.resource_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(d.resource_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(d.resource_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(d.resource_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(d.resource_count...` |
| 74.0 | `SELECT substr(metadata_created, 1, 4) AS created_year, COUNT(*) AS count FROM datasets d WHERE d.metadata_created IS NOT NULL GROUP BY substr(metadata_created, 1, 4)` |
| 72.0 | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count FROM datasets d GROUP BY COALESCE(theme_primary, '__none__')` |
| 67.0 | `SELECT COUNT(*) FILTER (WHERE harvested = 1) AS harvested,       COUNT(*) FILTER (WHERE harvested = 0) AS manual FROM datasets d` |
| 48.0 | `SELECT dy.year, COUNT(*) AS count FROM dataset_years dy JOIN datasets d ON d.id = dy.dataset_id AND dy.year <= 2026 GROUP BY dy.year` |
| 42.0 | `SELECT  COUNT(*) FILTER (WHERE tp.dataset_id IS NULL) AS none,  COUNT(*) FILTER (WHERE tp.has_pre1900) AS pre1900,  COUNT(*) FILTER (WHERE tp.has_post) AS post FROM datasets d LEFT JOIN (   SELECT dataset_id,    BOOL_OR(COALESCE(from_year, to_year) < 1900) AS has_pre1900,    BOOL_OR(COALESCE(to_year...` |
| 32.0 | `SELECT da.api_category AS api, COUNT(*) AS count FROM datasets d JOIN dataset_api da ON da.dataset_id = d.id GROUP BY da.api_category` |
| 15.0 | `SELECT DISTINCT year FROM dataset_years WHERE year <= 2026 ORDER BY year DESC` |
| 4.0 | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count        FROM datasets GROUP BY COALESCE(theme_primary, '__none__')` |
| 2.0 | `SELECT COUNT(*) AS n FROM datasets d` |
| 2.0 | `SELECT COUNT(*) AS n FROM datasets` |
| 1.0 | `SELECT d.ckan_id, d.title, d.name, d.org_slug,  d.org_display_name AS organisation,  d.metadata_created, d.metadata_modified, d.resource_count,  d.theme_primary, d.harvested, d.harvest_source_title, d.views FROM datasets d ORDER BY d.views DESC, d.id LIMIT %s OFFSET %s` |

## sort by resources desc
wall=166.6ms  render=34.7ms  (13 queries, parallel)

| ms | sql |
|---|---|
| 55.0 | `SELECT d.org_slug AS value,       COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug) AS name, COUNT(*) AS count FROM datasets d GROUP BY d.org_slug ORDER BY count DESC, LOWER(COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug))` |
| 46.0 | `SELECT dy.year, COUNT(*) AS count FROM dataset_years dy JOIN datasets d ON d.id = dy.dataset_id AND dy.year <= 2026 GROUP BY dy.year` |
| 43.0 | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count FROM datasets d GROUP BY COALESCE(theme_primary, '__none__')` |
| 39.0 | `SELECT COUNT(*) FILTER (WHERE harvested = 1) AS harvested,       COUNT(*) FILTER (WHERE harvested = 0) AS manual FROM datasets d` |
| 38.0 | `SELECT CASE WHEN COALESCE(d.resource_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(d.resource_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(d.resource_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(d.resource_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(d.resource_count...` |
| 37.0 | `SELECT  COUNT(*) FILTER (WHERE tp.dataset_id IS NULL) AS none,  COUNT(*) FILTER (WHERE tp.has_pre1900) AS pre1900,  COUNT(*) FILTER (WHERE tp.has_post) AS post FROM datasets d LEFT JOIN (   SELECT dataset_id,    BOOL_OR(COALESCE(from_year, to_year) < 1900) AS has_pre1900,    BOOL_OR(COALESCE(to_year...` |
| 35.0 | `SELECT d.ckan_id, d.title, d.name, d.org_slug,  d.org_display_name AS organisation,  d.metadata_created, d.metadata_modified, d.resource_count,  d.theme_primary, d.harvested, d.harvest_source_title, d.views FROM datasets d ORDER BY COALESCE(d.resource_count, 0) DESC, d.id LIMIT %s OFFSET %s` |
| 33.0 | `SELECT substr(metadata_created, 1, 4) AS created_year, COUNT(*) AS count FROM datasets d WHERE d.metadata_created IS NOT NULL GROUP BY substr(metadata_created, 1, 4)` |
| 28.0 | `SELECT da.api_category AS api, COUNT(*) AS count FROM datasets d JOIN dataset_api da ON da.dataset_id = d.id GROUP BY da.api_category` |
| 9.0 | `SELECT DISTINCT year FROM dataset_years WHERE year <= 2026 ORDER BY year DESC` |
| 4.0 | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count        FROM datasets GROUP BY COALESCE(theme_primary, '__none__')` |
| 1.0 | `SELECT COUNT(*) AS n FROM datasets d` |
| 1.0 | `SELECT COUNT(*) AS n FROM datasets` |

## filter by source=harvested
wall=337.2ms  render=35.9ms  (13 queries, parallel)

| ms | sql |
|---|---|
| 182.0 | `SELECT substr(metadata_created, 1, 4) AS created_year, COUNT(*) AS count FROM datasets d WHERE d.harvested = 1 AND d.metadata_created IS NOT NULL GROUP BY substr(metadata_created, 1, 4)` |
| 181.0 | `SELECT d.org_slug AS value,       COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug) AS name, COUNT(*) AS count FROM datasets d WHERE d.harvested = 1 GROUP BY d.org_slug ORDER BY count DESC, LOWER(COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug))` |
| 166.0 | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count FROM datasets d WHERE d.harvested = 1 GROUP BY COALESCE(theme_primary, '__none__')` |
| 151.0 | `SELECT  COUNT(*) FILTER (WHERE tp.dataset_id IS NULL) AS none,  COUNT(*) FILTER (WHERE tp.has_pre1900) AS pre1900,  COUNT(*) FILTER (WHERE tp.has_post) AS post FROM datasets d LEFT JOIN (   SELECT dataset_id,    BOOL_OR(COALESCE(from_year, to_year) < 1900) AS has_pre1900,    BOOL_OR(COALESCE(to_year...` |
| 141.0 | `SELECT da.api_category AS api, COUNT(*) AS count FROM datasets d JOIN dataset_api da ON da.dataset_id = d.id WHERE d.harvested = 1 GROUP BY da.api_category` |
| 112.0 | `SELECT dy.year, COUNT(*) AS count FROM dataset_years dy JOIN datasets d ON d.id = dy.dataset_id AND dy.year <= 2026 WHERE d.harvested = 1 GROUP BY dy.year` |
| 99.0 | `SELECT CASE WHEN COALESCE(d.resource_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(d.resource_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(d.resource_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(d.resource_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(d.resource_count...` |
| 28.0 | `SELECT COUNT(*) FILTER (WHERE harvested = 1) AS harvested,       COUNT(*) FILTER (WHERE harvested = 0) AS manual FROM datasets d` |
| 8.0 | `SELECT DISTINCT year FROM dataset_years WHERE year <= 2026 ORDER BY year DESC` |
| 4.0 | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count        FROM datasets GROUP BY COALESCE(theme_primary, '__none__')` |
| 2.0 | `SELECT COUNT(*) AS n FROM datasets` |
| 1.0 | `SELECT COUNT(*) AS n FROM datasets d WHERE d.harvested = 1` |
| 1.0 | `SELECT d.ckan_id, d.title, d.name, d.org_slug,  d.org_display_name AS organisation,  d.metadata_created, d.metadata_modified, d.resource_count,  d.theme_primary, d.harvested, d.harvest_source_title, d.views FROM datasets d WHERE d.harvested = 1 ORDER BY d.views DESC, d.id LIMIT %s OFFSET %s` |

## filter by theme=none
wall=269.6ms  render=35.3ms  (13 queries, parallel)

| ms | sql |
|---|---|
| 142.0 | `SELECT  COUNT(*) FILTER (WHERE tp.dataset_id IS NULL) AS none,  COUNT(*) FILTER (WHERE tp.has_pre1900) AS pre1900,  COUNT(*) FILTER (WHERE tp.has_post) AS post FROM datasets d LEFT JOIN (   SELECT dataset_id,    BOOL_OR(COALESCE(from_year, to_year) < 1900) AS has_pre1900,    BOOL_OR(COALESCE(to_year...` |
| 141.0 | `SELECT COUNT(*) FILTER (WHERE harvested = 1) AS harvested,       COUNT(*) FILTER (WHERE harvested = 0) AS manual FROM datasets d WHERE d.theme_primary IS NULL` |
| 141.0 | `SELECT da.api_category AS api, COUNT(*) AS count FROM datasets d JOIN dataset_api da ON da.dataset_id = d.id WHERE d.theme_primary IS NULL GROUP BY da.api_category` |
| 133.0 | `SELECT substr(metadata_created, 1, 4) AS created_year, COUNT(*) AS count FROM datasets d WHERE d.theme_primary IS NULL AND d.metadata_created IS NOT NULL GROUP BY substr(metadata_created, 1, 4)` |
| 80.0 | `SELECT dy.year, COUNT(*) AS count FROM dataset_years dy JOIN datasets d ON d.id = dy.dataset_id AND dy.year <= 2026 WHERE d.theme_primary IS NULL GROUP BY dy.year` |
| 75.0 | `SELECT CASE WHEN COALESCE(d.resource_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(d.resource_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(d.resource_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(d.resource_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(d.resource_count...` |
| 62.0 | `SELECT d.org_slug AS value,       COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug) AS name, COUNT(*) AS count FROM datasets d WHERE d.theme_primary IS NULL GROUP BY d.org_slug ORDER BY count DESC, LOWER(COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug))` |
| 30.0 | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count FROM datasets d GROUP BY COALESCE(theme_primary, '__none__')` |
| 9.0 | `SELECT DISTINCT year FROM dataset_years WHERE year <= 2026 ORDER BY year DESC` |
| 4.0 | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count        FROM datasets GROUP BY COALESCE(theme_primary, '__none__')` |
| 2.0 | `SELECT COUNT(*) AS n FROM datasets` |
| 1.0 | `SELECT COUNT(*) AS n FROM datasets d WHERE d.theme_primary IS NULL` |
| 1.0 | `SELECT d.ckan_id, d.title, d.name, d.org_slug,  d.org_display_name AS organisation,  d.metadata_created, d.metadata_modified, d.resource_count,  d.theme_primary, d.harvested, d.harvest_source_title, d.views FROM datasets d WHERE d.theme_primary IS NULL ORDER BY d.views DESC, d.id LIMIT %s OFFSET %s` |

## page 2
wall=134.0ms  render=33.0ms  (13 queries, parallel)

| ms | sql |
|---|---|
| 52.0 | `SELECT substr(metadata_created, 1, 4) AS created_year, COUNT(*) AS count FROM datasets d WHERE d.metadata_created IS NOT NULL GROUP BY substr(metadata_created, 1, 4)` |
| 47.0 | `SELECT d.org_slug AS value,       COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug) AS name, COUNT(*) AS count FROM datasets d GROUP BY d.org_slug ORDER BY count DESC, LOWER(COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug))` |
| 47.0 | `SELECT CASE WHEN COALESCE(d.resource_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(d.resource_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(d.resource_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(d.resource_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(d.resource_count...` |
| 46.0 | `SELECT dy.year, COUNT(*) AS count FROM dataset_years dy JOIN datasets d ON d.id = dy.dataset_id AND dy.year <= 2026 GROUP BY dy.year` |
| 41.0 | `SELECT COUNT(*) FILTER (WHERE harvested = 1) AS harvested,       COUNT(*) FILTER (WHERE harvested = 0) AS manual FROM datasets d` |
| 39.0 | `SELECT  COUNT(*) FILTER (WHERE tp.dataset_id IS NULL) AS none,  COUNT(*) FILTER (WHERE tp.has_pre1900) AS pre1900,  COUNT(*) FILTER (WHERE tp.has_post) AS post FROM datasets d LEFT JOIN (   SELECT dataset_id,    BOOL_OR(COALESCE(from_year, to_year) < 1900) AS has_pre1900,    BOOL_OR(COALESCE(to_year...` |
| 37.0 | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count FROM datasets d GROUP BY COALESCE(theme_primary, '__none__')` |
| 27.0 | `SELECT da.api_category AS api, COUNT(*) AS count FROM datasets d JOIN dataset_api da ON da.dataset_id = d.id GROUP BY da.api_category` |
| 8.0 | `SELECT DISTINCT year FROM dataset_years WHERE year <= 2026 ORDER BY year DESC` |
| 4.0 | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count        FROM datasets GROUP BY COALESCE(theme_primary, '__none__')` |
| 1.0 | `SELECT COUNT(*) AS n FROM datasets d` |
| 1.0 | `SELECT d.ckan_id, d.title, d.name, d.org_slug,  d.org_display_name AS organisation,  d.metadata_created, d.metadata_modified, d.resource_count,  d.theme_primary, d.harvested, d.harvest_source_title, d.views FROM datasets d ORDER BY d.views DESC, d.id LIMIT %s OFFSET %s` |
| 1.0 | `SELECT COUNT(*) AS n FROM datasets` |

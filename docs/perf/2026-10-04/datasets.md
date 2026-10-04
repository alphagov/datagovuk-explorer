# /datasets performance — 2026-10-04

| case | wall | sql | render |
|---|---|---|---|
| baseline | 390ms | 343ms | 47ms |
| sort by resources desc | 255ms | 215ms | 41ms |
| filter by source=harvested | 417ms | 382ms | 35ms |
| filter by theme=none | 268ms | 232ms | 36ms |
| page 2 | 213ms | 175ms | 39ms |


## baseline
wall=390.1ms  render=46.6ms  (15 queries, parallel)

| ms | thread | sql |
|---|---|---|
| 184.0 | main | `SELECT COUNT(*) FILTER (WHERE harvested = 1) AS harvested,       COUNT(*) FILTER (WHERE harvested = 0) AS manual FROM datasets d` |
| 106.0 | main | `SELECT DISTINCT org_slug FROM datasets` |
| 89.0 | main | `SELECT  COUNT(*) FILTER (WHERE NOT EXISTS (    SELECT 1 FROM temporal_periods tp WHERE tp.dataset_id = d.id  )) AS none,  COUNT(*) FILTER (WHERE    EXISTS (     SELECT 1 FROM temporal_periods tp     WHERE tp.dataset_id = d.id       AND COALESCE(tp.from_year, tp.to_year) < 1900   )) AS pre1900,  COUN...` |
| 70.0 | main | `SELECT CASE WHEN COALESCE(d.resource_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(d.resource_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(d.resource_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(d.resource_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(d.resource_count...` |
| 70.0 | main | `SELECT substr(metadata_created, 1, 4) AS created_year, COUNT(*) AS count FROM datasets d WHERE d.metadata_created IS NOT NULL GROUP BY substr(metadata_created, 1, 4)` |
| 67.0 | main | `SELECT d.org_slug AS value,       COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug) AS name, COUNT(*) AS count FROM datasets d GROUP BY d.org_slug ORDER BY count DESC, LOWER(COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug))` |
| 61.0 | main | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count FROM datasets d GROUP BY COALESCE(theme_primary, '__none__')` |
| 46.0 | main | `SELECT dy.year, COUNT(*) AS count FROM dataset_years dy JOIN datasets d ON d.id = dy.dataset_id AND dy.year <= 2026 GROUP BY dy.year` |
| 28.0 | main | `SELECT da.api_category AS api, COUNT(*) AS count FROM datasets d JOIN dataset_api da ON da.dataset_id = d.id GROUP BY da.api_category` |
| 14.0 | main | `SELECT DISTINCT year FROM dataset_years WHERE year <= 2026 ORDER BY year DESC` |
| 12.0 | main | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count        FROM datasets GROUP BY COALESCE(theme_primary, '__none__')` |
| 11.0 | main | `SELECT substr(metadata_created, 1, 4) AS year, COUNT(*) AS count        FROM datasets WHERE metadata_created IS NOT NULL        GROUP BY substr(metadata_created, 1, 4)` |
| 2.0 | main | `SELECT COUNT(*) AS n FROM datasets d` |
| 2.0 | main | `SELECT COUNT(*) AS n FROM datasets` |
| 1.0 | main | `SELECT d.ckan_id, d.title, d.name, d.org_slug,  d.org_display_name AS organisation,  d.metadata_created, d.metadata_modified, d.resource_count,  d.theme_primary, d.harvested, d.harvest_source_title, d.views FROM datasets d ORDER BY d.views DESC, d.id LIMIT %s OFFSET %s` |

## sort by resources desc
wall=255.4ms  render=40.7ms  (13 queries, parallel)

| ms | thread | sql |
|---|---|---|
| 157.0 | main | `SELECT COUNT(*) FILTER (WHERE harvested = 1) AS harvested,       COUNT(*) FILTER (WHERE harvested = 0) AS manual FROM datasets d` |
| 89.0 | main | `SELECT  COUNT(*) FILTER (WHERE NOT EXISTS (    SELECT 1 FROM temporal_periods tp WHERE tp.dataset_id = d.id  )) AS none,  COUNT(*) FILTER (WHERE    EXISTS (     SELECT 1 FROM temporal_periods tp     WHERE tp.dataset_id = d.id       AND COALESCE(tp.from_year, tp.to_year) < 1900   )) AS pre1900,  COUN...` |
| 59.0 | main | `SELECT d.org_slug AS value,       COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug) AS name, COUNT(*) AS count FROM datasets d GROUP BY d.org_slug ORDER BY count DESC, LOWER(COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug))` |
| 52.0 | main | `SELECT CASE WHEN COALESCE(d.resource_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(d.resource_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(d.resource_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(d.resource_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(d.resource_count...` |
| 46.0 | main | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count FROM datasets d GROUP BY COALESCE(theme_primary, '__none__')` |
| 46.0 | main | `SELECT dy.year, COUNT(*) AS count FROM dataset_years dy JOIN datasets d ON d.id = dy.dataset_id AND dy.year <= 2026 GROUP BY dy.year` |
| 39.0 | main | `SELECT d.ckan_id, d.title, d.name, d.org_slug,  d.org_display_name AS organisation,  d.metadata_created, d.metadata_modified, d.resource_count,  d.theme_primary, d.harvested, d.harvest_source_title, d.views FROM datasets d ORDER BY COALESCE(d.resource_count, 0) DESC, d.id LIMIT %s OFFSET %s` |
| 34.0 | main | `SELECT substr(metadata_created, 1, 4) AS created_year, COUNT(*) AS count FROM datasets d WHERE d.metadata_created IS NOT NULL GROUP BY substr(metadata_created, 1, 4)` |
| 28.0 | main | `SELECT da.api_category AS api, COUNT(*) AS count FROM datasets d JOIN dataset_api da ON da.dataset_id = d.id GROUP BY da.api_category` |
| 9.0 | main | `SELECT DISTINCT year FROM dataset_years WHERE year <= 2026 ORDER BY year DESC` |
| 4.0 | main | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count        FROM datasets GROUP BY COALESCE(theme_primary, '__none__')` |
| 2.0 | main | `SELECT COUNT(*) AS n FROM datasets` |
| 1.0 | main | `SELECT COUNT(*) AS n FROM datasets d` |

## filter by source=harvested
wall=417.1ms  render=34.8ms  (13 queries, parallel)

| ms | thread | sql |
|---|---|---|
| 166.0 | main | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count FROM datasets d WHERE d.harvested = 1 GROUP BY COALESCE(theme_primary, '__none__')` |
| 161.0 | main | `SELECT d.org_slug AS value,       COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug) AS name, COUNT(*) AS count FROM datasets d WHERE d.harvested = 1 GROUP BY d.org_slug ORDER BY count DESC, LOWER(COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug))` |
| 159.0 | main | `SELECT  COUNT(*) FILTER (WHERE NOT EXISTS (    SELECT 1 FROM temporal_periods tp WHERE tp.dataset_id = d.id  )) AS none,  COUNT(*) FILTER (WHERE    EXISTS (     SELECT 1 FROM temporal_periods tp     WHERE tp.dataset_id = d.id       AND COALESCE(tp.from_year, tp.to_year) < 1900   )) AS pre1900,  COUN...` |
| 150.0 | main | `SELECT COUNT(*) FILTER (WHERE harvested = 1) AS harvested,       COUNT(*) FILTER (WHERE harvested = 0) AS manual FROM datasets d` |
| 138.0 | main | `SELECT substr(metadata_created, 1, 4) AS created_year, COUNT(*) AS count FROM datasets d WHERE d.harvested = 1 AND d.metadata_created IS NOT NULL GROUP BY substr(metadata_created, 1, 4)` |
| 107.0 | main | `SELECT da.api_category AS api, COUNT(*) AS count FROM datasets d JOIN dataset_api da ON da.dataset_id = d.id WHERE d.harvested = 1 GROUP BY da.api_category` |
| 84.0 | main | `SELECT dy.year, COUNT(*) AS count FROM dataset_years dy JOIN datasets d ON d.id = dy.dataset_id AND dy.year <= 2026 WHERE d.harvested = 1 GROUP BY dy.year` |
| 79.0 | main | `SELECT CASE WHEN COALESCE(d.resource_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(d.resource_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(d.resource_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(d.resource_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(d.resource_count...` |
| 66.0 | main | `SELECT COUNT(*) AS n FROM datasets d WHERE d.harvested = 1` |
| 9.0 | main | `SELECT DISTINCT year FROM dataset_years WHERE year <= 2026 ORDER BY year DESC` |
| 4.0 | main | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count        FROM datasets GROUP BY COALESCE(theme_primary, '__none__')` |
| 2.0 | main | `SELECT COUNT(*) AS n FROM datasets` |
| 1.0 | main | `SELECT d.ckan_id, d.title, d.name, d.org_slug,  d.org_display_name AS organisation,  d.metadata_created, d.metadata_modified, d.resource_count,  d.theme_primary, d.harvested, d.harvest_source_title, d.views FROM datasets d WHERE d.harvested = 1 ORDER BY d.views DESC, d.id LIMIT %s OFFSET %s` |

## filter by theme=none
wall=267.9ms  render=35.7ms  (13 queries, parallel)

| ms | thread | sql |
|---|---|---|
| 164.0 | main | `SELECT  COUNT(*) FILTER (WHERE NOT EXISTS (    SELECT 1 FROM temporal_periods tp WHERE tp.dataset_id = d.id  )) AS none,  COUNT(*) FILTER (WHERE    EXISTS (     SELECT 1 FROM temporal_periods tp     WHERE tp.dataset_id = d.id       AND COALESCE(tp.from_year, tp.to_year) < 1900   )) AS pre1900,  COUN...` |
| 144.0 | main | `SELECT COUNT(*) FILTER (WHERE harvested = 1) AS harvested,       COUNT(*) FILTER (WHERE harvested = 0) AS manual FROM datasets d WHERE d.theme_primary IS NULL` |
| 140.0 | main | `SELECT substr(metadata_created, 1, 4) AS created_year, COUNT(*) AS count FROM datasets d WHERE d.theme_primary IS NULL AND d.metadata_created IS NOT NULL GROUP BY substr(metadata_created, 1, 4)` |
| 116.0 | main | `SELECT da.api_category AS api, COUNT(*) AS count FROM datasets d JOIN dataset_api da ON da.dataset_id = d.id WHERE d.theme_primary IS NULL GROUP BY da.api_category` |
| 83.0 | main | `SELECT dy.year, COUNT(*) AS count FROM dataset_years dy JOIN datasets d ON d.id = dy.dataset_id AND dy.year <= 2026 WHERE d.theme_primary IS NULL GROUP BY dy.year` |
| 76.0 | main | `SELECT CASE WHEN COALESCE(d.resource_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(d.resource_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(d.resource_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(d.resource_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(d.resource_count...` |
| 50.0 | main | `SELECT d.org_slug AS value,       COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug) AS name, COUNT(*) AS count FROM datasets d WHERE d.theme_primary IS NULL GROUP BY d.org_slug ORDER BY count DESC, LOWER(COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug))` |
| 34.0 | main | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count FROM datasets d GROUP BY COALESCE(theme_primary, '__none__')` |
| 8.0 | main | `SELECT DISTINCT year FROM dataset_years WHERE year <= 2026 ORDER BY year DESC` |
| 4.0 | main | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count        FROM datasets GROUP BY COALESCE(theme_primary, '__none__')` |
| 2.0 | main | `SELECT COUNT(*) AS n FROM datasets` |
| 1.0 | main | `SELECT COUNT(*) AS n FROM datasets d WHERE d.theme_primary IS NULL` |
| 1.0 | main | `SELECT d.ckan_id, d.title, d.name, d.org_slug,  d.org_display_name AS organisation,  d.metadata_created, d.metadata_modified, d.resource_count,  d.theme_primary, d.harvested, d.harvest_source_title, d.views FROM datasets d WHERE d.theme_primary IS NULL ORDER BY d.views DESC, d.id LIMIT %s OFFSET %s` |

## page 2
wall=213.1ms  render=38.5ms  (13 queries, parallel)

| ms | thread | sql |
|---|---|---|
| 153.0 | main | `SELECT COUNT(*) FILTER (WHERE harvested = 1) AS harvested,       COUNT(*) FILTER (WHERE harvested = 0) AS manual FROM datasets d` |
| 87.0 | main | `SELECT  COUNT(*) FILTER (WHERE NOT EXISTS (    SELECT 1 FROM temporal_periods tp WHERE tp.dataset_id = d.id  )) AS none,  COUNT(*) FILTER (WHERE    EXISTS (     SELECT 1 FROM temporal_periods tp     WHERE tp.dataset_id = d.id       AND COALESCE(tp.from_year, tp.to_year) < 1900   )) AS pre1900,  COUN...` |
| 63.0 | main | `SELECT d.org_slug AS value,       COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug) AS name, COUNT(*) AS count FROM datasets d GROUP BY d.org_slug ORDER BY count DESC, LOWER(COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug))` |
| 48.0 | main | `SELECT substr(metadata_created, 1, 4) AS created_year, COUNT(*) AS count FROM datasets d WHERE d.metadata_created IS NOT NULL GROUP BY substr(metadata_created, 1, 4)` |
| 46.0 | main | `SELECT CASE WHEN COALESCE(d.resource_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(d.resource_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(d.resource_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(d.resource_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(d.resource_count...` |
| 45.0 | main | `SELECT dy.year, COUNT(*) AS count FROM dataset_years dy JOIN datasets d ON d.id = dy.dataset_id AND dy.year <= 2026 GROUP BY dy.year` |
| 33.0 | main | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count FROM datasets d GROUP BY COALESCE(theme_primary, '__none__')` |
| 29.0 | main | `SELECT da.api_category AS api, COUNT(*) AS count FROM datasets d JOIN dataset_api da ON da.dataset_id = d.id GROUP BY da.api_category` |
| 9.0 | main | `SELECT DISTINCT year FROM dataset_years WHERE year <= 2026 ORDER BY year DESC` |
| 4.0 | main | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count        FROM datasets GROUP BY COALESCE(theme_primary, '__none__')` |
| 2.0 | main | `SELECT COUNT(*) AS n FROM datasets d` |
| 1.0 | main | `SELECT d.ckan_id, d.title, d.name, d.org_slug,  d.org_display_name AS organisation,  d.metadata_created, d.metadata_modified, d.resource_count,  d.theme_primary, d.harvested, d.harvest_source_title, d.views FROM datasets d ORDER BY d.views DESC, d.id LIMIT %s OFFSET %s` |
| 1.0 | main | `SELECT COUNT(*) AS n FROM datasets` |

# /organisations performance — 2026-10-04

| case | wall | render |
|---|---|---|
| baseline | 462ms | 44ms |
| sort by dataset_count desc | 298ms | 29ms |
| filter by datasets=0 | 295ms | 29ms |
| filter by last_published=never | 294ms | 29ms |
| page 2 | 280ms | 28ms |


## baseline
wall=462.3ms  render=44.0ms  (9 queries)

| ms | sql |
|---|---|
| 175.0 | `SELECT l.org_slug,  COUNT(*) FILTER (WHERE lcr.ok) * 100.0 / NULLIF(COUNT(*), 0) AS link_health FROM links l LEFT JOIN link_check_results lcr ON l.url = lcr.url GROUP BY l.org_slug` |
| 142.0 | `SELECT org_slug,               SUM(resource_count) AS total_resources,               SUM(views) AS total_views,               MAX(metadata_created) AS last_published        FROM datasets GROUP BY org_slug` |
| 90.0 | `SELECT substr(created, 1, 4) AS year, COUNT(*) AS count        FROM organisations WHERE created ~ '^\d{4}'        GROUP BY substr(created, 1, 4)` |
| 2.0 | `SELECT o.slug, o.name, o.display_name, o.package_count, o.type, o.state,       o.approval_status, o.created, o.title,       COALESCE(a.total_resources, 0) AS total_resources,       COALESCE(a.total_views, 0) AS total_views,       a.last_published FROM organisations o LEFT JOIN mv_org_aggregates a ON...` |
| 1.0 | `SELECT COUNT(*) AS n FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug` |
| 1.0 | `SELECT substr(o.created, 1, 4) AS created_year, COUNT(*) AS count FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE substr(o.created, 1, 4) ~ '^\d{4}' GROUP BY substr(o.created, 1, 4)` |
| 1.0 | `SELECT substr(a.last_published, 1, 4) AS last_published_year, COUNT(*) AS count FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE a.last_published IS NOT NULL GROUP BY substr(a.last_published, 1, 4)` |
| 0.0 | `SELECT COUNT(*) AS n FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE a.last_published IS NULL` |
| 0.0 | `SELECT CASE WHEN COALESCE(o.package_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(o.package_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(o.package_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(o.package_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(o.package_count, 0) ...` |

## sort by dataset_count desc
wall=298.1ms  render=29.4ms  (9 queries)

| ms | sql |
|---|---|
| 156.0 | `SELECT l.org_slug,  COUNT(*) FILTER (WHERE lcr.ok) * 100.0 / NULLIF(COUNT(*), 0) AS link_health FROM links l LEFT JOIN link_check_results lcr ON l.url = lcr.url GROUP BY l.org_slug` |
| 106.0 | `SELECT org_slug,               SUM(resource_count) AS total_resources,               SUM(views) AS total_views,               MAX(metadata_created) AS last_published        FROM datasets GROUP BY org_slug` |
| 2.0 | `SELECT o.slug, o.name, o.display_name, o.package_count, o.type, o.state,       o.approval_status, o.created, o.title,       COALESCE(a.total_resources, 0) AS total_resources,       COALESCE(a.total_views, 0) AS total_views,       a.last_published FROM organisations o LEFT JOIN mv_org_aggregates a ON...` |
| 1.0 | `SELECT substr(created, 1, 4) AS year, COUNT(*) AS count        FROM organisations WHERE created ~ '^\d{4}'        GROUP BY substr(created, 1, 4)` |
| 1.0 | `SELECT substr(o.created, 1, 4) AS created_year, COUNT(*) AS count FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE substr(o.created, 1, 4) ~ '^\d{4}' GROUP BY substr(o.created, 1, 4)` |
| 1.0 | `SELECT substr(a.last_published, 1, 4) AS last_published_year, COUNT(*) AS count FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE a.last_published IS NOT NULL GROUP BY substr(a.last_published, 1, 4)` |
| 0.0 | `SELECT COUNT(*) AS n FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug` |
| 0.0 | `SELECT COUNT(*) AS n FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE a.last_published IS NULL` |
| 0.0 | `SELECT CASE WHEN COALESCE(o.package_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(o.package_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(o.package_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(o.package_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(o.package_count, 0) ...` |

## filter by datasets=0
wall=295.5ms  render=28.7ms  (9 queries)

| ms | sql |
|---|---|
| 161.0 | `SELECT l.org_slug,  COUNT(*) FILTER (WHERE lcr.ok) * 100.0 / NULLIF(COUNT(*), 0) AS link_health FROM links l LEFT JOIN link_check_results lcr ON l.url = lcr.url GROUP BY l.org_slug` |
| 101.0 | `SELECT org_slug,               SUM(resource_count) AS total_resources,               SUM(views) AS total_views,               MAX(metadata_created) AS last_published        FROM datasets GROUP BY org_slug` |
| 1.0 | `SELECT substr(created, 1, 4) AS year, COUNT(*) AS count        FROM organisations WHERE created ~ '^\d{4}'        GROUP BY substr(created, 1, 4)` |
| 1.0 | `SELECT COUNT(*) AS n FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE COALESCE(o.package_count, 0) BETWEEN %s AND %s` |
| 1.0 | `SELECT o.slug, o.name, o.display_name, o.package_count, o.type, o.state,       o.approval_status, o.created, o.title,       COALESCE(a.total_resources, 0) AS total_resources,       COALESCE(a.total_views, 0) AS total_views,       a.last_published FROM organisations o LEFT JOIN mv_org_aggregates a ON...` |
| 1.0 | `SELECT substr(a.last_published, 1, 4) AS last_published_year, COUNT(*) AS count FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE COALESCE(o.package_count, 0) BETWEEN %s AND %s AND a.last_published IS NOT NULL GROUP BY substr(a.last_published, 1, 4)` |
| 0.0 | `SELECT substr(o.created, 1, 4) AS created_year, COUNT(*) AS count FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE COALESCE(o.package_count, 0) BETWEEN %s AND %s AND substr(o.created, 1, 4) ~ '^\d{4}' GROUP BY substr(o.created, 1, 4)` |
| 0.0 | `SELECT COUNT(*) AS n FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE COALESCE(o.package_count, 0) BETWEEN %s AND %s AND a.last_published IS NULL` |
| 0.0 | `SELECT CASE WHEN COALESCE(o.package_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(o.package_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(o.package_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(o.package_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(o.package_count, 0) ...` |

## filter by last_published=never
wall=293.7ms  render=28.7ms  (9 queries)

| ms | sql |
|---|---|
| 159.0 | `SELECT l.org_slug,  COUNT(*) FILTER (WHERE lcr.ok) * 100.0 / NULLIF(COUNT(*), 0) AS link_health FROM links l LEFT JOIN link_check_results lcr ON l.url = lcr.url GROUP BY l.org_slug` |
| 100.0 | `SELECT org_slug,               SUM(resource_count) AS total_resources,               SUM(views) AS total_views,               MAX(metadata_created) AS last_published        FROM datasets GROUP BY org_slug` |
| 1.0 | `SELECT substr(created, 1, 4) AS year, COUNT(*) AS count        FROM organisations WHERE created ~ '^\d{4}'        GROUP BY substr(created, 1, 4)` |
| 1.0 | `SELECT COUNT(*) AS n FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE a.last_published IS NULL` |
| 1.0 | `SELECT o.slug, o.name, o.display_name, o.package_count, o.type, o.state,       o.approval_status, o.created, o.title,       COALESCE(a.total_resources, 0) AS total_resources,       COALESCE(a.total_views, 0) AS total_views,       a.last_published FROM organisations o LEFT JOIN mv_org_aggregates a ON...` |
| 1.0 | `SELECT substr(o.created, 1, 4) AS created_year, COUNT(*) AS count FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE a.last_published IS NULL AND substr(o.created, 1, 4) ~ '^\d{4}' GROUP BY substr(o.created, 1, 4)` |
| 1.0 | `SELECT substr(a.last_published, 1, 4) AS last_published_year, COUNT(*) AS count FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE a.last_published IS NOT NULL GROUP BY substr(a.last_published, 1, 4)` |
| 0.0 | `SELECT COUNT(*) AS n FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE a.last_published IS NULL` |
| 0.0 | `SELECT CASE WHEN COALESCE(o.package_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(o.package_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(o.package_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(o.package_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(o.package_count, 0) ...` |

## page 2
wall=279.8ms  render=28.2ms  (9 queries)

| ms | sql |
|---|---|
| 147.0 | `SELECT l.org_slug,  COUNT(*) FILTER (WHERE lcr.ok) * 100.0 / NULLIF(COUNT(*), 0) AS link_health FROM links l LEFT JOIN link_check_results lcr ON l.url = lcr.url GROUP BY l.org_slug` |
| 97.0 | `SELECT org_slug,               SUM(resource_count) AS total_resources,               SUM(views) AS total_views,               MAX(metadata_created) AS last_published        FROM datasets GROUP BY org_slug` |
| 2.0 | `SELECT o.slug, o.name, o.display_name, o.package_count, o.type, o.state,       o.approval_status, o.created, o.title,       COALESCE(a.total_resources, 0) AS total_resources,       COALESCE(a.total_views, 0) AS total_views,       a.last_published FROM organisations o LEFT JOIN mv_org_aggregates a ON...` |
| 1.0 | `SELECT substr(created, 1, 4) AS year, COUNT(*) AS count        FROM organisations WHERE created ~ '^\d{4}'        GROUP BY substr(created, 1, 4)` |
| 1.0 | `SELECT COUNT(*) AS n FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug` |
| 1.0 | `SELECT substr(o.created, 1, 4) AS created_year, COUNT(*) AS count FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE substr(o.created, 1, 4) ~ '^\d{4}' GROUP BY substr(o.created, 1, 4)` |
| 1.0 | `SELECT substr(a.last_published, 1, 4) AS last_published_year, COUNT(*) AS count FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE a.last_published IS NOT NULL GROUP BY substr(a.last_published, 1, 4)` |
| 0.0 | `SELECT COUNT(*) AS n FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE a.last_published IS NULL` |
| 0.0 | `SELECT CASE WHEN COALESCE(o.package_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(o.package_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(o.package_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(o.package_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(o.package_count, 0) ...` |

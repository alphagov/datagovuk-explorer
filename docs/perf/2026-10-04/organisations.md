# /organisations performance — 2026-10-04

| case | wall | render |
|---|---|---|
| baseline | 160ms | 44ms |
| sort by dataset_count desc | 42ms | 22ms |
| filter by datasets=0 | 34ms | 21ms |
| filter by last_published=never | 40ms | 21ms |
| page 2 | 44ms | 24ms |


## baseline
wall=159.6ms  render=44.4ms  (9 queries)

| ms | sql |
|---|---|
| 98.0 | `SELECT substr(created, 1, 4) AS year, COUNT(*) AS count        FROM organisations WHERE created ~ '^\d{4}'        GROUP BY substr(created, 1, 4)` |
| 3.0 | `SELECT o.slug, o.name, o.display_name, o.package_count, o.type, o.state,       o.approval_status, o.created, o.title,       COALESCE(a.total_resources, 0) AS total_resources,       COALESCE(a.total_views, 0) AS total_views,       a.last_published FROM organisations o LEFT JOIN mv_org_aggregates a ON...` |
| 2.0 | `SELECT * FROM mv_org_aggregates` |
| 1.0 | `SELECT COUNT(*) AS n FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug` |
| 1.0 | `SELECT org_slug, link_health FROM org_link_health` |
| 1.0 | `SELECT substr(o.created, 1, 4) AS created_year, COUNT(*) AS count FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE substr(o.created, 1, 4) ~ '^\d{4}' GROUP BY substr(o.created, 1, 4)` |
| 1.0 | `SELECT substr(a.last_published, 1, 4) AS last_published_year, COUNT(*) AS count FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE a.last_published IS NOT NULL GROUP BY substr(a.last_published, 1, 4)` |
| 1.0 | `SELECT COUNT(*) AS n FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE a.last_published IS NULL` |
| 1.0 | `SELECT CASE WHEN COALESCE(o.package_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(o.package_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(o.package_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(o.package_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(o.package_count, 0) ...` |

## sort by dataset_count desc
wall=42.3ms  render=21.7ms  (9 queries)

| ms | sql |
|---|---|
| 6.0 | `SELECT o.slug, o.name, o.display_name, o.package_count, o.type, o.state,       o.approval_status, o.created, o.title,       COALESCE(a.total_resources, 0) AS total_resources,       COALESCE(a.total_views, 0) AS total_views,       a.last_published FROM organisations o LEFT JOIN mv_org_aggregates a ON...` |
| 2.0 | `SELECT substr(created, 1, 4) AS year, COUNT(*) AS count        FROM organisations WHERE created ~ '^\d{4}'        GROUP BY substr(created, 1, 4)` |
| 2.0 | `SELECT * FROM mv_org_aggregates` |
| 2.0 | `SELECT org_slug, link_health FROM org_link_health` |
| 2.0 | `SELECT substr(o.created, 1, 4) AS created_year, COUNT(*) AS count FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE substr(o.created, 1, 4) ~ '^\d{4}' GROUP BY substr(o.created, 1, 4)` |
| 2.0 | `SELECT substr(a.last_published, 1, 4) AS last_published_year, COUNT(*) AS count FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE a.last_published IS NOT NULL GROUP BY substr(a.last_published, 1, 4)` |
| 2.0 | `SELECT COUNT(*) AS n FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE a.last_published IS NULL` |
| 1.0 | `SELECT COUNT(*) AS n FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug` |
| 1.0 | `SELECT CASE WHEN COALESCE(o.package_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(o.package_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(o.package_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(o.package_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(o.package_count, 0) ...` |

## filter by datasets=0
wall=34.2ms  render=20.9ms  (9 queries)

| ms | sql |
|---|---|
| 3.0 | `SELECT org_slug, link_health FROM org_link_health` |
| 2.0 | `SELECT * FROM mv_org_aggregates` |
| 1.0 | `SELECT substr(created, 1, 4) AS year, COUNT(*) AS count        FROM organisations WHERE created ~ '^\d{4}'        GROUP BY substr(created, 1, 4)` |
| 1.0 | `SELECT COUNT(*) AS n FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE COALESCE(o.package_count, 0) BETWEEN %s AND %s` |
| 1.0 | `SELECT o.slug, o.name, o.display_name, o.package_count, o.type, o.state,       o.approval_status, o.created, o.title,       COALESCE(a.total_resources, 0) AS total_resources,       COALESCE(a.total_views, 0) AS total_views,       a.last_published FROM organisations o LEFT JOIN mv_org_aggregates a ON...` |
| 1.0 | `SELECT substr(o.created, 1, 4) AS created_year, COUNT(*) AS count FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE COALESCE(o.package_count, 0) BETWEEN %s AND %s AND substr(o.created, 1, 4) ~ '^\d{4}' GROUP BY substr(o.created, 1, 4)` |
| 1.0 | `SELECT substr(a.last_published, 1, 4) AS last_published_year, COUNT(*) AS count FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE COALESCE(o.package_count, 0) BETWEEN %s AND %s AND a.last_published IS NOT NULL GROUP BY substr(a.last_published, 1, 4)` |
| 1.0 | `SELECT COUNT(*) AS n FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE COALESCE(o.package_count, 0) BETWEEN %s AND %s AND a.last_published IS NULL` |
| 1.0 | `SELECT CASE WHEN COALESCE(o.package_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(o.package_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(o.package_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(o.package_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(o.package_count, 0) ...` |

## filter by last_published=never
wall=39.6ms  render=21.1ms  (9 queries)

| ms | sql |
|---|---|
| 3.0 | `SELECT substr(o.created, 1, 4) AS created_year, COUNT(*) AS count FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE a.last_published IS NULL AND substr(o.created, 1, 4) ~ '^\d{4}' GROUP BY substr(o.created, 1, 4)` |
| 2.0 | `SELECT substr(created, 1, 4) AS year, COUNT(*) AS count        FROM organisations WHERE created ~ '^\d{4}'        GROUP BY substr(created, 1, 4)` |
| 2.0 | `SELECT * FROM mv_org_aggregates` |
| 2.0 | `SELECT COUNT(*) AS n FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE a.last_published IS NULL` |
| 2.0 | `SELECT org_slug, link_health FROM org_link_health` |
| 2.0 | `SELECT o.slug, o.name, o.display_name, o.package_count, o.type, o.state,       o.approval_status, o.created, o.title,       COALESCE(a.total_resources, 0) AS total_resources,       COALESCE(a.total_views, 0) AS total_views,       a.last_published FROM organisations o LEFT JOIN mv_org_aggregates a ON...` |
| 2.0 | `SELECT substr(a.last_published, 1, 4) AS last_published_year, COUNT(*) AS count FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE a.last_published IS NOT NULL GROUP BY substr(a.last_published, 1, 4)` |
| 2.0 | `SELECT COUNT(*) AS n FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE a.last_published IS NULL` |
| 2.0 | `SELECT CASE WHEN COALESCE(o.package_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(o.package_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(o.package_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(o.package_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(o.package_count, 0) ...` |

## page 2
wall=44.4ms  render=23.8ms  (9 queries)

| ms | sql |
|---|---|
| 5.0 | `SELECT o.slug, o.name, o.display_name, o.package_count, o.type, o.state,       o.approval_status, o.created, o.title,       COALESCE(a.total_resources, 0) AS total_resources,       COALESCE(a.total_views, 0) AS total_views,       a.last_published FROM organisations o LEFT JOIN mv_org_aggregates a ON...` |
| 2.0 | `SELECT substr(created, 1, 4) AS year, COUNT(*) AS count        FROM organisations WHERE created ~ '^\d{4}'        GROUP BY substr(created, 1, 4)` |
| 2.0 | `SELECT * FROM mv_org_aggregates` |
| 2.0 | `SELECT org_slug, link_health FROM org_link_health` |
| 2.0 | `SELECT substr(o.created, 1, 4) AS created_year, COUNT(*) AS count FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE substr(o.created, 1, 4) ~ '^\d{4}' GROUP BY substr(o.created, 1, 4)` |
| 2.0 | `SELECT substr(a.last_published, 1, 4) AS last_published_year, COUNT(*) AS count FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE a.last_published IS NOT NULL GROUP BY substr(a.last_published, 1, 4)` |
| 2.0 | `SELECT COUNT(*) AS n FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug WHERE a.last_published IS NULL` |
| 1.0 | `SELECT COUNT(*) AS n FROM organisations o LEFT JOIN mv_org_aggregates a ON a.org_slug = o.slug` |
| 1.0 | `SELECT CASE WHEN COALESCE(o.package_count, 0) BETWEEN 0 AND 0 THEN '0' WHEN COALESCE(o.package_count, 0) BETWEEN 1 AND 10 THEN '1-10' WHEN COALESCE(o.package_count, 0) BETWEEN 11 AND 50 THEN '11-50' WHEN COALESCE(o.package_count, 0) BETWEEN 51 AND 100 THEN '51-100' WHEN COALESCE(o.package_count, 0) ...` |

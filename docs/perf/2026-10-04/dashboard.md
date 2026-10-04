# / (dashboard) performance — 2026-10-04

| case | wall | render |
|---|---|---|
| cold (cache miss) | 655ms | 34ms |
| warm (cache hit) | 21ms | 20ms |


## cold (cache miss)
wall=654.9ms  render=34.0ms  (15 queries, parallel)

| ms | sql |
|---|---|
| 383.0 | `SELECT COUNT(*) AS n FROM datasets WHERE notes IS NOT NULL AND TRIM(notes) != '' AND LENGTH(TRIM(notes)) < 80` |
| 379.0 | `SELECT COUNT(*) AS n FROM datasets WHERE (title LIKE '%%withdrawn%%' OR notes LIKE '%%dataset has been withdrawn%%' OR notes LIKE '%%no longer updated and has been retired%%' OR notes LIKE '%%record has been retired%%' OR notes LIKE '%%dataset has been retired%%')` |
| 257.0 | `SELECT COUNT(*) AS n FROM datasets WHERE (notes IS NULL OR TRIM(notes) = '')` |
| 234.0 | `SELECT org_slug, MAX(metadata_created) AS last_published        FROM datasets WHERE metadata_created IS NOT NULL        GROUP BY org_slug` |
| 198.0 | `SELECT COUNT(*) AS n             FROM link_check_results             WHERE final_url IS NOT NULL               AND final_url != url               AND checked_at IS NOT NULL               AND final_url IN (                 SELECT final_url FROM link_check_results                 WHERE final_url IS NO...` |
| 186.0 | `SELECT          COUNT(*) AS total,          COUNT(DISTINCT org_slug) AS orgs,          SUM(CASE WHEN host IS NULL THEN 1 ELSE 0 END) AS no_url,          SUM(CASE WHEN host = 'data.gov.uk' OR host LIKE '%%.data.gov.uk' THEN 1 ELSE 0 END) AS internal,          SUM(CASE WHEN format_norm IS NULL OR form...` |
| 177.0 | `SELECT  COUNT(*) AS total,  COUNT(*) FILTER (WHERE lcr.ok = false OR l.url IS NULL OR l.url = '') AS errors,  COUNT(*) FILTER (WHERE lcr.ok) AS resolved FROM links l LEFT JOIN link_check_results lcr ON l.url = lcr.url WHERE lcr.checked_at IS NOT NULL OR l.url IS NULL OR l.url = ''` |
| 134.0 | `SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count        FROM datasets GROUP BY COALESCE(theme_primary, '__none__')` |
| 129.0 | `SELECT slug, name, display_name, package_count, type, state,               approval_status, created, title          FROM organisations          ORDER BY LOWER(display_name), slug` |
| 123.0 | `SELECT COUNT(*) AS n FROM datasets` |
| 79.0 | `SELECT COUNT(*) AS n FROM datasets WHERE title IS NOT NULL AND TRIM(title) != '' AND LENGTH(TRIM(title)) < 20` |
| 75.0 | `SELECT COUNT(*) AS n FROM (                SELECT url FROM links                WHERE url IS NOT NULL AND url != ''                GROUP BY url                HAVING COUNT(DISTINCT dataset_id) > 1              )` |
| 53.0 | `SELECT COALESCE(SUM(n - 1), 0) AS n FROM (                SELECT COUNT(*) AS n FROM dataset_content_hash                GROUP BY content_hash                HAVING COUNT(*) > 1              ) sub` |
| 51.0 | `SELECT COUNT(*) AS n FROM links WHERE (name IS NULL OR name = '') AND (description IS NULL OR description = '')` |
| 33.0 | `SELECT COUNT(*) AS n FROM datasets WHERE resource_count = 0` |

## warm (cache hit)
wall=20.5ms  render=20.1ms  (0 queries, parallel)

| ms | sql |
|---|---|

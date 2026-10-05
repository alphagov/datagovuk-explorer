# /links/status performance — 2026-10-05

| case | wall | render |
|---|---|---|
| baseline | 348ms | 94ms |
| sort by status desc | 250ms | 79ms |
| filter by category=NOT_FOUND | 346ms | 78ms |
| filter by status=error | 335ms | 71ms |
| filter by harvested=harvested | 527ms | 82ms |
| domains expanded | 260ms | 85ms |
| page 2 | 238ms | 70ms |


## baseline
wall=348.2ms  render=94.1ms  (9 queries)

| ms | sql |
|---|---|
| 73.0 | `SELECT  COUNT(*) AS total,  COUNT(*) FILTER (WHERE ok = false OR url IS NULL OR url = '') AS errors,  COUNT(*) FILTER (WHERE ok) AS resolved FROM mv_link_status WHERE checked_at IS NOT NULL OR url IS NULL OR url = ''` |
| 49.0 | `SELECT org_slug AS value, publisher_name AS name, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND org_slug <> '' GROUP BY org_slug, publisher_name ORDER BY count DESC, LOWER(publisher_name)` |
| 26.0 | `SELECT (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR' WHEN http_status >= 500 THEN 'SERVER_ERROR' WHEN error LIKE 'dns:%%' OR (error LIKE 'playwright:%%' AND error ILIKE '%%ERR...` |
| 22.0 | `SELECT host AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND host IS NOT NULL AND host <> '' GROUP BY host ORDER BY count DESC, LOWER(host)` |
| 20.0 | `SELECT CASE WHEN COALESCE(ok, false) THEN 'ok' ELSE 'error' END AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY COALESCE(ok, false) ORDER BY COALESCE(ok, false) DESC` |
| 17.0 | `SELECT harvest_state AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY 1` |
| 14.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND COALESCE(host, '') = ''` |
| 14.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '')` |
| 3.0 | `SELECT url AS resource_url,  ckan_id, dataset_title AS package_name,  resource_id, org_slug AS org_name, org_slug,  http_status AS status,  (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLI...` |

## sort by status desc
wall=249.5ms  render=79.4ms  (9 queries)

| ms | sql |
|---|---|
| 46.0 | `SELECT org_slug AS value, publisher_name AS name, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND org_slug <> '' GROUP BY org_slug, publisher_name ORDER BY count DESC, LOWER(publisher_name)` |
| 21.0 | `SELECT (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR' WHEN http_status >= 500 THEN 'SERVER_ERROR' WHEN error LIKE 'dns:%%' OR (error LIKE 'playwright:%%' AND error ILIKE '%%ERR...` |
| 21.0 | `SELECT host AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND host IS NOT NULL AND host <> '' GROUP BY host ORDER BY count DESC, LOWER(host)` |
| 18.0 | `SELECT CASE WHEN COALESCE(ok, false) THEN 'ok' ELSE 'error' END AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY COALESCE(ok, false) ORDER BY COALESCE(ok, false) DESC` |
| 17.0 | `SELECT  COUNT(*) AS total,  COUNT(*) FILTER (WHERE ok = false OR url IS NULL OR url = '') AS errors,  COUNT(*) FILTER (WHERE ok) AS resolved FROM mv_link_status WHERE checked_at IS NOT NULL OR url IS NULL OR url = ''` |
| 17.0 | `SELECT harvest_state AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY 1` |
| 13.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND COALESCE(host, '') = ''` |
| 13.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '')` |
| 1.0 | `SELECT url AS resource_url,  ckan_id, dataset_title AS package_name,  resource_id, org_slug AS org_name, org_slug,  http_status AS status,  (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLI...` |

## filter by category=NOT_FOUND
wall=346.0ms  render=77.6ms  (15 queries)

| ms | sql |
|---|---|
| 47.0 | `SELECT org_slug AS value, publisher_name AS name, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND org_slug <> '' GROUP BY org_slug, publisher_name ORDER BY count DESC, LOWER(publisher_name)` |
| 21.0 | `SELECT host AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND host IS NOT NULL AND host <> '' GROUP BY host ORDER BY count DESC, LOWER(host)` |
| 20.0 | `SELECT (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR' WHEN http_status >= 500 THEN 'SERVER_ERROR' WHEN error LIKE 'dns:%%' OR (error LIKE 'playwright:%%' AND error ILIKE '%%ERR...` |
| 20.0 | `SELECT (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR' WHEN http_status >= 500 THEN 'SERVER_ERROR' WHEN error LIKE 'dns:%%' OR (error LIKE 'playwright:%%' AND error ILIKE '%%ERR...` |
| 18.0 | `SELECT org_slug AS value, publisher_name AS name, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN ...` |
| 17.0 | `SELECT  COUNT(*) AS total,  COUNT(*) FILTER (WHERE ok = false OR url IS NULL OR url = '') AS errors,  COUNT(*) FILTER (WHERE ok) AS resolved FROM mv_link_status WHERE checked_at IS NOT NULL OR url IS NULL OR url = ''` |
| 17.0 | `SELECT CASE WHEN COALESCE(ok, false) THEN 'ok' ELSE 'error' END AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY COALESCE(ok, false) ORDER BY COALESCE(ok, false) DESC` |
| 17.0 | `SELECT harvest_state AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY 1` |
| 16.0 | `SELECT host AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR' WHEN ht...` |
| 15.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR' WHEN http_status >= 500 TH...` |
| 15.0 | `SELECT CASE WHEN COALESCE(ok, false) THEN 'ok' ELSE 'error' END AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND...` |
| 15.0 | `SELECT harvest_state AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR...` |
| 14.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR' WHEN http_status >= 500 TH...` |
| 13.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND COALESCE(host, '') = ''` |
| 3.0 | `SELECT url AS resource_url,  ckan_id, dataset_title AS package_name,  resource_id, org_slug AS org_name, org_slug,  http_status AS status,  (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLI...` |

## filter by status=error
wall=335.1ms  render=70.9ms  (15 queries)

| ms | sql |
|---|---|
| 49.0 | `SELECT org_slug AS value, publisher_name AS name, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND org_slug <> '' GROUP BY org_slug, publisher_name ORDER BY count DESC, LOWER(publisher_name)` |
| 25.0 | `SELECT (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR' WHEN http_status >= 500 THEN 'SERVER_ERROR' WHEN error LIKE 'dns:%%' OR (error LIKE 'playwright:%%' AND error ILIKE '%%ERR...` |
| 21.0 | `SELECT (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR' WHEN http_status >= 500 THEN 'SERVER_ERROR' WHEN error LIKE 'dns:%%' OR (error LIKE 'playwright:%%' AND error ILIKE '%%ERR...` |
| 20.0 | `SELECT host AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND host IS NOT NULL AND host <> '' GROUP BY host ORDER BY count DESC, LOWER(host)` |
| 17.0 | `SELECT  COUNT(*) AS total,  COUNT(*) FILTER (WHERE ok = false OR url IS NULL OR url = '') AS errors,  COUNT(*) FILTER (WHERE ok) AS resolved FROM mv_link_status WHERE checked_at IS NOT NULL OR url IS NULL OR url = ''` |
| 17.0 | `SELECT CASE WHEN COALESCE(ok, false) THEN 'ok' ELSE 'error' END AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY COALESCE(ok, false) ORDER BY COALESCE(ok, false) DESC` |
| 17.0 | `SELECT harvest_state AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY 1` |
| 17.0 | `SELECT CASE WHEN COALESCE(ok, false) THEN 'ok' ELSE 'error' END AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY COALESCE(ok, false) ORDER BY COALESCE(ok, false) DESC` |
| 15.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND ok = false AND COALESCE(host, '') = ''` |
| 14.0 | `SELECT host AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND ok = false AND host IS NOT NULL AND host <> '' GROUP BY host ORDER BY count DESC, LOWER(host)` |
| 13.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND COALESCE(host, '') = ''` |
| 13.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND ok = false` |
| 13.0 | `SELECT harvest_state AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND ok = false GROUP BY 1` |
| 7.0 | `SELECT org_slug AS value, publisher_name AS name, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND ok = false AND org_slug <> '' GROUP BY org_slug, publisher_name ORDER BY count DESC, LOWER(publisher_name)` |
| 3.0 | `SELECT url AS resource_url,  ckan_id, dataset_title AS package_name,  resource_id, org_slug AS org_name, org_slug,  http_status AS status,  (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLI...` |

## filter by harvested=harvested
wall=526.7ms  render=81.5ms  (15 queries)

| ms | sql |
|---|---|
| 93.0 | `SELECT url AS resource_url,  ckan_id, dataset_title AS package_name,  resource_id, org_slug AS org_name, org_slug,  http_status AS status,  (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLI...` |
| 49.0 | `SELECT org_slug AS value, publisher_name AS name, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND org_slug <> '' GROUP BY org_slug, publisher_name ORDER BY count DESC, LOWER(publisher_name)` |
| 36.0 | `SELECT org_slug AS value, publisher_name AS name, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND harvest_state = 'harvested' AND org_slug <> '' GROUP BY org_slug, publisher_name ORDER BY count DESC, LOWER(publisher_name)` |
| 33.0 | `SELECT (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR' WHEN http_status >= 500 THEN 'SERVER_ERROR' WHEN error LIKE 'dns:%%' OR (error LIKE 'playwright:%%' AND error ILIKE '%%ERR...` |
| 33.0 | `SELECT host AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND harvest_state = 'harvested' AND host IS NOT NULL AND host <> '' GROUP BY host ORDER BY count DESC, LOWER(host)` |
| 27.0 | `SELECT CASE WHEN COALESCE(ok, false) THEN 'ok' ELSE 'error' END AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND harvest_state = 'harvested' GROUP BY COALESCE(ok, false) ORDER BY COALESCE(ok, false) DESC` |
| 22.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND harvest_state = 'harvested'` |
| 21.0 | `SELECT (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR' WHEN http_status >= 500 THEN 'SERVER_ERROR' WHEN error LIKE 'dns:%%' OR (error LIKE 'playwright:%%' AND error ILIKE '%%ERR...` |
| 21.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND harvest_state = 'harvested' AND COALESCE(host, '') = ''` |
| 20.0 | `SELECT host AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND host IS NOT NULL AND host <> '' GROUP BY host ORDER BY count DESC, LOWER(host)` |
| 18.0 | `SELECT  COUNT(*) AS total,  COUNT(*) FILTER (WHERE ok = false OR url IS NULL OR url = '') AS errors,  COUNT(*) FILTER (WHERE ok) AS resolved FROM mv_link_status WHERE checked_at IS NOT NULL OR url IS NULL OR url = ''` |
| 18.0 | `SELECT harvest_state AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY 1` |
| 17.0 | `SELECT CASE WHEN COALESCE(ok, false) THEN 'ok' ELSE 'error' END AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY COALESCE(ok, false) ORDER BY COALESCE(ok, false) DESC` |
| 17.0 | `SELECT harvest_state AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY 1` |
| 13.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND COALESCE(host, '') = ''` |

## domains expanded
wall=260.4ms  render=85.1ms  (9 queries)

| ms | sql |
|---|---|
| 47.0 | `SELECT org_slug AS value, publisher_name AS name, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND org_slug <> '' GROUP BY org_slug, publisher_name ORDER BY count DESC, LOWER(publisher_name)` |
| 22.0 | `SELECT (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR' WHEN http_status >= 500 THEN 'SERVER_ERROR' WHEN error LIKE 'dns:%%' OR (error LIKE 'playwright:%%' AND error ILIKE '%%ERR...` |
| 20.0 | `SELECT host AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND host IS NOT NULL AND host <> '' GROUP BY host ORDER BY count DESC, LOWER(host)` |
| 17.0 | `SELECT CASE WHEN COALESCE(ok, false) THEN 'ok' ELSE 'error' END AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY COALESCE(ok, false) ORDER BY COALESCE(ok, false) DESC` |
| 17.0 | `SELECT harvest_state AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY 1` |
| 16.0 | `SELECT  COUNT(*) AS total,  COUNT(*) FILTER (WHERE ok = false OR url IS NULL OR url = '') AS errors,  COUNT(*) FILTER (WHERE ok) AS resolved FROM mv_link_status WHERE checked_at IS NOT NULL OR url IS NULL OR url = ''` |
| 13.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND COALESCE(host, '') = ''` |
| 13.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '')` |
| 2.0 | `SELECT url AS resource_url,  ckan_id, dataset_title AS package_name,  resource_id, org_slug AS org_name, org_slug,  http_status AS status,  (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLI...` |

## page 2
wall=237.6ms  render=70.5ms  (9 queries)

| ms | sql |
|---|---|
| 46.0 | `SELECT org_slug AS value, publisher_name AS name, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND org_slug <> '' GROUP BY org_slug, publisher_name ORDER BY count DESC, LOWER(publisher_name)` |
| 21.0 | `SELECT host AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND host IS NOT NULL AND host <> '' GROUP BY host ORDER BY count DESC, LOWER(host)` |
| 20.0 | `SELECT (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR' WHEN http_status >= 500 THEN 'SERVER_ERROR' WHEN error LIKE 'dns:%%' OR (error LIKE 'playwright:%%' AND error ILIKE '%%ERR...` |
| 17.0 | `SELECT CASE WHEN COALESCE(ok, false) THEN 'ok' ELSE 'error' END AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY COALESCE(ok, false) ORDER BY COALESCE(ok, false) DESC` |
| 17.0 | `SELECT harvest_state AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY 1` |
| 15.0 | `SELECT  COUNT(*) AS total,  COUNT(*) FILTER (WHERE ok = false OR url IS NULL OR url = '') AS errors,  COUNT(*) FILTER (WHERE ok) AS resolved FROM mv_link_status WHERE checked_at IS NOT NULL OR url IS NULL OR url = ''` |
| 13.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND COALESCE(host, '') = ''` |
| 13.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '')` |
| 1.0 | `SELECT url AS resource_url,  ckan_id, dataset_title AS package_name,  resource_id, org_slug AS org_name, org_slug,  http_status AS status,  (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLI...` |

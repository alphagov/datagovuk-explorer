# /links/status performance — 2026-10-05

5 reps per case; wall/render are medians, and each case warms the DB page cache first so case order does not leak in.

| case | wall | render |
|---|---|---|
| baseline | 228ms | 22ms |
| sort by status desc | 267ms | 36ms |
| filter by category=NOT_FOUND | 334ms | 6ms |
| filter by status=error | 251ms | 16ms |
| filter by harvested=harvested | 382ms | 21ms |
| domains expanded | 256ms | 42ms |
| page 2 | 260ms | 49ms |


## baseline
wall median=227.5ms (min=218.4, max=228.7)  render=21.5ms  (9 queries)

| ms | sql |
|---|---|
| 49.0 | `SELECT org_slug AS value, publisher_name AS name, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND org_slug <> '' GROUP BY org_slug, publisher_name ORDER BY count DESC, LOWER(publisher_name)` |
| 46.0 | `SELECT (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR' WHEN http_status >= 500 THEN 'SERVER_ERROR' WHEN error LIKE 'dns:%%' OR (error LIKE 'playwright:%%' AND error ILIKE '%%ERR...` |
| 21.0 | `SELECT host AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND host IS NOT NULL AND host <> '' GROUP BY host ORDER BY count DESC, LOWER(host)` |
| 18.0 | `SELECT CASE WHEN COALESCE(ok, false) THEN 'ok' ELSE 'error' END AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY COALESCE(ok, false) ORDER BY COALESCE(ok, false) DESC` |
| 18.0 | `SELECT harvest_state AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY 1` |
| 16.0 | `SELECT  COUNT(*) AS total,  COUNT(*) FILTER (WHERE ok = false OR url IS NULL OR url = '') AS errors,  COUNT(*) FILTER (WHERE ok) AS resolved FROM mv_link_status WHERE checked_at IS NOT NULL OR url IS NULL OR url = ''` |
| 14.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND COALESCE(host, '') = ''` |
| 14.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '')` |
| 1.0 | `SELECT url AS resource_url,  ckan_id, dataset_title AS package_name,  resource_id, org_slug AS org_name, org_slug,  http_status AS status,  (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLI...` |

## sort by status desc
wall median=266.7ms (min=262.9, max=289.0)  render=36.1ms  (9 queries)

| ms | sql |
|---|---|
| 49.0 | `SELECT org_slug AS value, publisher_name AS name, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND org_slug <> '' GROUP BY org_slug, publisher_name ORDER BY count DESC, LOWER(publisher_name)` |
| 44.0 | `SELECT (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR' WHEN http_status >= 500 THEN 'SERVER_ERROR' WHEN error LIKE 'dns:%%' OR (error LIKE 'playwright:%%' AND error ILIKE '%%ERR...` |
| 32.0 | `SELECT url AS resource_url,  ckan_id, dataset_title AS package_name,  resource_id, org_slug AS org_name, org_slug,  http_status AS status,  (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLI...` |
| 21.0 | `SELECT host AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND host IS NOT NULL AND host <> '' GROUP BY host ORDER BY count DESC, LOWER(host)` |
| 18.0 | `SELECT CASE WHEN COALESCE(ok, false) THEN 'ok' ELSE 'error' END AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY COALESCE(ok, false) ORDER BY COALESCE(ok, false) DESC` |
| 17.0 | `SELECT harvest_state AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY 1` |
| 16.0 | `SELECT  COUNT(*) AS total,  COUNT(*) FILTER (WHERE ok = false OR url IS NULL OR url = '') AS errors,  COUNT(*) FILTER (WHERE ok) AS resolved FROM mv_link_status WHERE checked_at IS NOT NULL OR url IS NULL OR url = ''` |
| 15.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '')` |
| 14.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND COALESCE(host, '') = ''` |

## filter by category=NOT_FOUND
wall median=333.6ms (min=332.2, max=336.1)  render=5.9ms  (15 queries)

| ms | sql |
|---|---|
| 49.0 | `SELECT org_slug AS value, publisher_name AS name, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND org_slug <> '' GROUP BY org_slug, publisher_name ORDER BY count DESC, LOWER(publisher_name)` |
| 43.0 | `SELECT (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR' WHEN http_status >= 500 THEN 'SERVER_ERROR' WHEN error LIKE 'dns:%%' OR (error LIKE 'playwright:%%' AND error ILIKE '%%ERR...` |
| 43.0 | `SELECT (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR' WHEN http_status >= 500 THEN 'SERVER_ERROR' WHEN error LIKE 'dns:%%' OR (error LIKE 'playwright:%%' AND error ILIKE '%%ERR...` |
| 21.0 | `SELECT host AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND host IS NOT NULL AND host <> '' GROUP BY host ORDER BY count DESC, LOWER(host)` |
| 18.0 | `SELECT CASE WHEN COALESCE(ok, false) THEN 'ok' ELSE 'error' END AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY COALESCE(ok, false) ORDER BY COALESCE(ok, false) DESC` |
| 18.0 | `SELECT harvest_state AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY 1` |
| 18.0 | `SELECT org_slug AS value, publisher_name AS name, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN ...` |
| 17.0 | `SELECT  COUNT(*) AS total,  COUNT(*) FILTER (WHERE ok = false OR url IS NULL OR url = '') AS errors,  COUNT(*) FILTER (WHERE ok) AS resolved FROM mv_link_status WHERE checked_at IS NOT NULL OR url IS NULL OR url = ''` |
| 17.0 | `SELECT host AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR' WHEN ht...` |
| 16.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR' WHEN http_status >= 500 TH...` |
| 16.0 | `SELECT CASE WHEN COALESCE(ok, false) THEN 'ok' ELSE 'error' END AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND...` |
| 16.0 | `SELECT harvest_state AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR...` |
| 14.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND COALESCE(host, '') = ''` |
| 14.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR' WHEN http_status >= 500 TH...` |
| 3.0 | `SELECT url AS resource_url,  ckan_id, dataset_title AS package_name,  resource_id, org_slug AS org_name, org_slug,  http_status AS status,  (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLI...` |

## filter by status=error
wall median=251.1ms (min=247.0, max=253.4)  render=16.0ms  (15 queries)

| ms | sql |
|---|---|
| 49.0 | `SELECT org_slug AS value, publisher_name AS name, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND org_slug <> '' GROUP BY org_slug, publisher_name ORDER BY count DESC, LOWER(publisher_name)` |
| 45.0 | `SELECT (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR' WHEN http_status >= 500 THEN 'SERVER_ERROR' WHEN error LIKE 'dns:%%' OR (error LIKE 'playwright:%%' AND error ILIKE '%%ERR...` |
| 21.0 | `SELECT host AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND host IS NOT NULL AND host <> '' GROUP BY host ORDER BY count DESC, LOWER(host)` |
| 18.0 | `SELECT  COUNT(*) AS total,  COUNT(*) FILTER (WHERE ok = false OR url IS NULL OR url = '') AS errors,  COUNT(*) FILTER (WHERE ok) AS resolved FROM mv_link_status WHERE checked_at IS NOT NULL OR url IS NULL OR url = ''` |
| 18.0 | `SELECT harvest_state AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY 1` |
| 18.0 | `SELECT CASE WHEN COALESCE(ok, false) THEN 'ok' ELSE 'error' END AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY COALESCE(ok, false) ORDER BY COALESCE(ok, false) DESC` |
| 17.0 | `SELECT CASE WHEN COALESCE(ok, false) THEN 'ok' ELSE 'error' END AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY COALESCE(ok, false) ORDER BY COALESCE(ok, false) DESC` |
| 14.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND COALESCE(host, '') = ''` |
| 7.0 | `SELECT (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR' WHEN http_status >= 500 THEN 'SERVER_ERROR' WHEN error LIKE 'dns:%%' OR (error LIKE 'playwright:%%' AND error ILIKE '%%ERR...` |
| 6.0 | `SELECT host AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND ok = false AND host IS NOT NULL AND host <> '' GROUP BY host ORDER BY count DESC, LOWER(host)` |
| 6.0 | `SELECT org_slug AS value, publisher_name AS name, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND ok = false AND org_slug <> '' GROUP BY org_slug, publisher_name ORDER BY count DESC, LOWER(publisher_name)` |
| 4.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND ok = false` |
| 4.0 | `SELECT harvest_state AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND ok = false GROUP BY 1` |
| 3.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND ok = false AND COALESCE(host, '') = ''` |
| 1.0 | `SELECT url AS resource_url,  ckan_id, dataset_title AS package_name,  resource_id, org_slug AS org_name, org_slug,  http_status AS status,  (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLI...` |

## filter by harvested=harvested
wall median=381.9ms (min=378.4, max=494.1)  render=21.2ms  (15 queries)

| ms | sql |
|---|---|
| 50.0 | `SELECT org_slug AS value, publisher_name AS name, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND org_slug <> '' GROUP BY org_slug, publisher_name ORDER BY count DESC, LOWER(publisher_name)` |
| 44.0 | `SELECT (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR' WHEN http_status >= 500 THEN 'SERVER_ERROR' WHEN error LIKE 'dns:%%' OR (error LIKE 'playwright:%%' AND error ILIKE '%%ERR...` |
| 44.0 | `SELECT org_slug AS value, publisher_name AS name, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND harvest_state = 'harvested' AND org_slug <> '' GROUP BY org_slug, publisher_name ORDER BY count DESC, LOWER(publisher_name)` |
| 40.0 | `SELECT (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR' WHEN http_status >= 500 THEN 'SERVER_ERROR' WHEN error LIKE 'dns:%%' OR (error LIKE 'playwright:%%' AND error ILIKE '%%ERR...` |
| 23.0 | `SELECT host AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND host IS NOT NULL AND host <> '' GROUP BY host ORDER BY count DESC, LOWER(host)` |
| 20.0 | `SELECT host AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND harvest_state = 'harvested' AND host IS NOT NULL AND host <> '' GROUP BY host ORDER BY count DESC, LOWER(host)` |
| 18.0 | `SELECT CASE WHEN COALESCE(ok, false) THEN 'ok' ELSE 'error' END AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY COALESCE(ok, false) ORDER BY COALESCE(ok, false) DESC` |
| 18.0 | `SELECT harvest_state AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY 1` |
| 18.0 | `SELECT CASE WHEN COALESCE(ok, false) THEN 'ok' ELSE 'error' END AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND harvest_state = 'harvested' GROUP BY COALESCE(ok, false) ORDER BY COALESCE(ok, false) DESC` |
| 18.0 | `SELECT harvest_state AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY 1` |
| 16.0 | `SELECT  COUNT(*) AS total,  COUNT(*) FILTER (WHERE ok = false OR url IS NULL OR url = '') AS errors,  COUNT(*) FILTER (WHERE ok) AS resolved FROM mv_link_status WHERE checked_at IS NOT NULL OR url IS NULL OR url = ''` |
| 15.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND harvest_state = 'harvested'` |
| 15.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND harvest_state = 'harvested' AND COALESCE(host, '') = ''` |
| 14.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND COALESCE(host, '') = ''` |
| 2.0 | `SELECT url AS resource_url,  ckan_id, dataset_title AS package_name,  resource_id, org_slug AS org_name, org_slug,  http_status AS status,  (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLI...` |

## domains expanded
wall median=256.5ms (min=229.4, max=264.2)  render=41.8ms  (9 queries)

| ms | sql |
|---|---|
| 51.0 | `SELECT org_slug AS value, publisher_name AS name, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND org_slug <> '' GROUP BY org_slug, publisher_name ORDER BY count DESC, LOWER(publisher_name)` |
| 43.0 | `SELECT (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR' WHEN http_status >= 500 THEN 'SERVER_ERROR' WHEN error LIKE 'dns:%%' OR (error LIKE 'playwright:%%' AND error ILIKE '%%ERR...` |
| 20.0 | `SELECT host AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND host IS NOT NULL AND host <> '' GROUP BY host ORDER BY count DESC, LOWER(host)` |
| 19.0 | `SELECT harvest_state AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY 1` |
| 17.0 | `SELECT CASE WHEN COALESCE(ok, false) THEN 'ok' ELSE 'error' END AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY COALESCE(ok, false) ORDER BY COALESCE(ok, false) DESC` |
| 17.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '')` |
| 16.0 | `SELECT  COUNT(*) AS total,  COUNT(*) FILTER (WHERE ok = false OR url IS NULL OR url = '') AS errors,  COUNT(*) FILTER (WHERE ok) AS resolved FROM mv_link_status WHERE checked_at IS NOT NULL OR url IS NULL OR url = ''` |
| 15.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND COALESCE(host, '') = ''` |
| 3.0 | `SELECT url AS resource_url,  ckan_id, dataset_title AS package_name,  resource_id, org_slug AS org_name, org_slug,  http_status AS status,  (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLI...` |

## page 2
wall median=260.2ms (min=232.3, max=268.8)  render=48.8ms  (9 queries)

| ms | sql |
|---|---|
| 51.0 | `SELECT org_slug AS value, publisher_name AS name, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND org_slug <> '' GROUP BY org_slug, publisher_name ORDER BY count DESC, LOWER(publisher_name)` |
| 44.0 | `SELECT (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR' WHEN http_status >= 500 THEN 'SERVER_ERROR' WHEN error LIKE 'dns:%%' OR (error LIKE 'playwright:%%' AND error ILIKE '%%ERR...` |
| 22.0 | `SELECT host AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND host IS NOT NULL AND host <> '' GROUP BY host ORDER BY count DESC, LOWER(host)` |
| 18.0 | `SELECT  COUNT(*) AS total,  COUNT(*) FILTER (WHERE ok = false OR url IS NULL OR url = '') AS errors,  COUNT(*) FILTER (WHERE ok) AS resolved FROM mv_link_status WHERE checked_at IS NOT NULL OR url IS NULL OR url = ''` |
| 18.0 | `SELECT harvest_state AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY 1` |
| 17.0 | `SELECT CASE WHEN COALESCE(ok, false) THEN 'ok' ELSE 'error' END AS value, COUNT(*) AS count FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') GROUP BY COALESCE(ok, false) ORDER BY COALESCE(ok, false) DESC` |
| 15.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '')` |
| 14.0 | `SELECT COUNT(*) AS n FROM mv_link_status WHERE (checked_at IS NOT NULL OR url IS NULL OR url = '') AND COALESCE(host, '') = ''` |
| 2.0 | `SELECT url AS resource_url,  ckan_id, dataset_title AS package_name,  resource_id, org_slug AS org_name, org_slug,  http_status AS status,  (CASE WHEN ok THEN 'OK' WHEN http_status = 404 THEN 'NOT_FOUND' WHEN http_status = 410 THEN 'GONE' WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLI...` |

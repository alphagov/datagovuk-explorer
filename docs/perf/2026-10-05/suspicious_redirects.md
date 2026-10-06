# /report/links-suspicious-redirects performance — 2026-10-05

5 reps per case; wall/render are medians, and each case warms the DB page cache first so case order does not leak in.

| case | wall | render |
|---|---|---|
| baseline | 539ms | 6ms |
| sort by org_count desc | 527ms | 5ms |
| sort by destination asc | 523ms | 8ms |
| filter by org=nhs-digital | 724ms | 6ms |
| page 2 | 533ms | 5ms |
| detail (top destination) | 80ms | 9ms |


## baseline
wall median=538.9ms (min=521.1, max=580.9)  render=5.7ms  (3 queries)

| ms | sql |
|---|---|
| 196.0 | `SELECT lcr.final_url,                        COUNT(*) AS link_count,                        COUNT(DISTINCT l.org_slug) AS org_count                 FROM links l                 JOIN link_check_results lcr ON l.url = lcr.url                 WHERE lcr.final_url IS NOT NULL                   AND lcr.fi...` |
| 185.0 | `SELECT l.org_slug AS slug, l.org_display_name AS name,                          COUNT(DISTINCT lcr.final_url) AS count                     FROM links l                     JOIN link_check_results lcr ON l.url = lcr.url                     WHERE lcr.final_url IS NOT NULL                       AND lcr...` |
| 152.0 | `SELECT COUNT(*) AS n FROM (             SELECT lcr.final_url             FROM links l             JOIN link_check_results lcr ON l.url = lcr.url             WHERE lcr.final_url IS NOT NULL               AND lcr.final_url != lcr.url               AND lcr.checked_at IS NOT NULL             GROUP BY lc...` |

## sort by org_count desc
wall median=527.0ms (min=516.7, max=635.2)  render=5.3ms  (3 queries)

| ms | sql |
|---|---|
| 197.0 | `SELECT l.org_slug AS slug, l.org_display_name AS name,                          COUNT(DISTINCT lcr.final_url) AS count                     FROM links l                     JOIN link_check_results lcr ON l.url = lcr.url                     WHERE lcr.final_url IS NOT NULL                       AND lcr...` |
| 180.0 | `SELECT lcr.final_url,                        COUNT(*) AS link_count,                        COUNT(DISTINCT l.org_slug) AS org_count                 FROM links l                 JOIN link_check_results lcr ON l.url = lcr.url                 WHERE lcr.final_url IS NOT NULL                   AND lcr.fi...` |
| 144.0 | `SELECT COUNT(*) AS n FROM (             SELECT lcr.final_url             FROM links l             JOIN link_check_results lcr ON l.url = lcr.url             WHERE lcr.final_url IS NOT NULL               AND lcr.final_url != lcr.url               AND lcr.checked_at IS NOT NULL             GROUP BY lc...` |

## sort by destination asc
wall median=522.6ms (min=511.8, max=594.2)  render=7.5ms  (3 queries)

| ms | sql |
|---|---|
| 197.0 | `SELECT l.org_slug AS slug, l.org_display_name AS name,                          COUNT(DISTINCT lcr.final_url) AS count                     FROM links l                     JOIN link_check_results lcr ON l.url = lcr.url                     WHERE lcr.final_url IS NOT NULL                       AND lcr...` |
| 185.0 | `SELECT lcr.final_url,                        COUNT(*) AS link_count,                        COUNT(DISTINCT l.org_slug) AS org_count                 FROM links l                 JOIN link_check_results lcr ON l.url = lcr.url                 WHERE lcr.final_url IS NOT NULL                   AND lcr.fi...` |
| 137.0 | `SELECT COUNT(*) AS n FROM (             SELECT lcr.final_url             FROM links l             JOIN link_check_results lcr ON l.url = lcr.url             WHERE lcr.final_url IS NOT NULL               AND lcr.final_url != lcr.url               AND lcr.checked_at IS NOT NULL             GROUP BY lc...` |

## filter by org=nhs-digital
wall median=724.3ms (min=703.9, max=738.6)  render=6.3ms  (4 queries)

| ms | sql |
|---|---|
| 198.0 | `SELECT l.org_slug AS slug, l.org_display_name AS name,                          COUNT(DISTINCT lcr.final_url) AS count                     FROM links l                     JOIN link_check_results lcr ON l.url = lcr.url                     WHERE lcr.final_url IS NOT NULL                       AND lcr...` |
| 189.0 | `SELECT l.org_slug AS slug, l.org_display_name AS name,                          COUNT(DISTINCT lcr.final_url) AS count                     FROM links l                     JOIN link_check_results lcr ON l.url = lcr.url                     WHERE lcr.final_url IS NOT NULL                       AND lcr...` |
| 184.0 | `SELECT lcr.final_url,                        COUNT(*) AS link_count,                        COUNT(DISTINCT l.org_slug) AS org_count                 FROM links l                 JOIN link_check_results lcr ON l.url = lcr.url                 WHERE lcr.final_url IS NOT NULL                   AND lcr.fi...` |
| 146.0 | `SELECT COUNT(*) AS n FROM (             SELECT lcr.final_url             FROM links l             JOIN link_check_results lcr ON l.url = lcr.url             WHERE lcr.final_url IS NOT NULL               AND lcr.final_url != lcr.url               AND lcr.checked_at IS NOT NULL             GROUP BY lc...` |

## page 2
wall median=533.2ms (min=517.6, max=896.0)  render=4.8ms  (3 queries)

| ms | sql |
|---|---|
| 199.0 | `SELECT l.org_slug AS slug, l.org_display_name AS name,                          COUNT(DISTINCT lcr.final_url) AS count                     FROM links l                     JOIN link_check_results lcr ON l.url = lcr.url                     WHERE lcr.final_url IS NOT NULL                       AND lcr...` |
| 190.0 | `SELECT lcr.final_url,                        COUNT(*) AS link_count,                        COUNT(DISTINCT l.org_slug) AS org_count                 FROM links l                 JOIN link_check_results lcr ON l.url = lcr.url                 WHERE lcr.final_url IS NOT NULL                   AND lcr.fi...` |
| 136.0 | `SELECT COUNT(*) AS n FROM (             SELECT lcr.final_url             FROM links l             JOIN link_check_results lcr ON l.url = lcr.url             WHERE lcr.final_url IS NOT NULL               AND lcr.final_url != lcr.url               AND lcr.checked_at IS NOT NULL             GROUP BY lc...` |

## detail (top destination)
wall median=79.5ms (min=63.7, max=80.4)  render=9.5ms  (2 queries)

| ms | sql |
|---|---|
| 35.0 | `SELECT l.id, l.dataset_id, l.org_slug, l.org_display_name, l.dataset_title, l.name, l.description, l.url, l.host, l.format_norm AS format,                     (SELECT ckan_id FROM datasets WHERE id = l.dataset_id) AS ckan_id                 FROM links l                 JOIN link_check_results lcr ON...` |
| 33.0 | `SELECT COUNT(*) AS n                 FROM links l                 JOIN link_check_results lcr ON l.url = lcr.url                 WHERE lcr.final_url = %s` |

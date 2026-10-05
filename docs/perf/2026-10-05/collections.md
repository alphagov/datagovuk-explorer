# /collections performance — 2026-10-05

| case | wall | render |
|---|---|---|
| baseline | 133ms | 39ms |
| sort by title asc | 28ms | 25ms |
| filter by collection=environment | 26ms | 24ms |
| sort by related desc | 24ms | 22ms |
| page 2 | 26ms | 24ms |


## baseline
wall=132.8ms  render=38.5ms  (4 queries)

| ms | sql |
|---|---|
| 88.0 | `SELECT c.collection, COUNT(*) AS count FROM collection_pages c GROUP BY c.collection ORDER BY c.collection` |
| 1.0 | `SELECT COUNT(*) AS n FROM collection_pages c` |
| 1.0 | `SELECT c.slug, c.collection, c.title,  c.page_last_updated, c.views, c.related_count AS related FROM collection_pages c ORDER BY COALESCE(c.views, 0) DESC, c.slug LIMIT %s OFFSET %s` |
| 0.0 | `SELECT COUNT(*) AS n FROM collection_pages` |

## sort by title asc
wall=27.7ms  render=24.8ms  (4 queries)

| ms | sql |
|---|---|
| 1.0 | `SELECT c.collection, COUNT(*) AS count FROM collection_pages c GROUP BY c.collection ORDER BY c.collection` |
| 1.0 | `SELECT c.slug, c.collection, c.title,  c.page_last_updated, c.views, c.related_count AS related FROM collection_pages c ORDER BY LOWER(COALESCE(c.title, '')) ASC, c.slug LIMIT %s OFFSET %s` |
| 0.0 | `SELECT COUNT(*) AS n FROM collection_pages c` |
| 0.0 | `SELECT COUNT(*) AS n FROM collection_pages` |

## filter by collection=environment
wall=25.9ms  render=24.0ms  (4 queries)

| ms | sql |
|---|---|
| 1.0 | `SELECT c.collection, COUNT(*) AS count FROM collection_pages c GROUP BY c.collection ORDER BY c.collection` |
| 0.0 | `SELECT COUNT(*) AS n FROM collection_pages c WHERE c.collection = %s` |
| 0.0 | `SELECT c.slug, c.collection, c.title,  c.page_last_updated, c.views, c.related_count AS related FROM collection_pages c WHERE c.collection = %s ORDER BY COALESCE(c.views, 0) DESC, c.slug LIMIT %s OFFSET %s` |
| 0.0 | `SELECT COUNT(*) AS n FROM collection_pages` |

## sort by related desc
wall=24.1ms  render=22.1ms  (4 queries)

| ms | sql |
|---|---|
| 1.0 | `SELECT c.collection, COUNT(*) AS count FROM collection_pages c GROUP BY c.collection ORDER BY c.collection` |
| 1.0 | `SELECT c.slug, c.collection, c.title,  c.page_last_updated, c.views, c.related_count AS related FROM collection_pages c ORDER BY COALESCE(c.related_count, 0) DESC, c.slug LIMIT %s OFFSET %s` |
| 0.0 | `SELECT COUNT(*) AS n FROM collection_pages c` |
| 0.0 | `SELECT COUNT(*) AS n FROM collection_pages` |

## page 2
wall=26.1ms  render=24.3ms  (4 queries)

| ms | sql |
|---|---|
| 0.0 | `SELECT c.collection, COUNT(*) AS count FROM collection_pages c GROUP BY c.collection ORDER BY c.collection` |
| 0.0 | `SELECT COUNT(*) AS n FROM collection_pages c` |
| 0.0 | `SELECT c.slug, c.collection, c.title,  c.page_last_updated, c.views, c.related_count AS related FROM collection_pages c ORDER BY COALESCE(c.views, 0) DESC, c.slug LIMIT %s OFFSET %s` |
| 0.0 | `SELECT COUNT(*) AS n FROM collection_pages` |

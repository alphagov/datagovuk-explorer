# Link checker plan

Check every URL in the `links` table using a HEAD → GET → Playwright fallback
chain, store results in a new `link_check_results` table. Resumable and testable.

---

## What we're building

A standalone Python script `scripts/check_links.py` that:

1. Reads all distinct valid URLs from `links` not yet in `link_check_results`
2. Checks each URL: HEAD first, then GET if needed, then Playwright (Chromium)
3. Writes results to `link_check_results` as they finish
4. Logs progress every 30 s; safe to interrupt and rerun

---

## Schema

New table `link_check_results`, owned by migration `0016`:

```sql
CREATE TABLE link_check_results (
    url          TEXT PRIMARY KEY,
    checked_at   TEXT NOT NULL,       -- ISO timestamp
    method       TEXT,                -- HEAD | GET | PLAYWRIGHT | SKIPPED | ERROR
    ok           BOOLEAN,
    http_status  INTEGER,             -- NULL when no HTTP response
    final_url    TEXT,                -- after redirects
    error        TEXT
);
```

Keyed by URL (not `link_id`) because multiple links can share the same URL —
check once, store once. The app joins `links ON links.url = link_check_results.url`.

---

## Script structure

```
is_checkable_url(url)       pure function — valid scheme, parseable, not blank
HostGate                    rate limiter, one per host
    acquire(host)           waits until the host's slot is free
check_url(url, *, ...)      HEAD → GET → Playwright chain; fetch_fn and pw_fn
                            are injected so tests can replace them with mocks.
                            fetch_fn defaults to a single shared httpx.AsyncClient
                            (connection pooling requires one shared client)
load_urls(db, *, ...)       returns unchecked URLs via LEFT JOIN; --force skips filter
writer(queue, db)           drains asyncio.Queue and upserts results to DB
main()                      parse args → load URLs → run workers + writer
```

### Check chain

```
HEAD
  └─ 2xx/3xx    → ok
  └─ 404/410    → broken  (skip GET and Playwright)
  └─ timeout    → skip GET, try Playwright
  └─ other      → try GET
     GET
       └─ 2xx/3xx  → ok
       └─ 404/410  → broken  (skip Playwright)
       └─ timeout  → broken  (skip Playwright)
       └─ other    → try Playwright
          PLAYWRIGHT
            └─ 2xx/3xx or download  → ok
            └─ error                → broken
```

**Headers:** HEAD and GET both send a browser User-Agent and `Accept: */*`.
Without a real UA many servers return 403 or drop the connection.

**429:** record as `ok=False, http_status=429` but don't fall through to GET or
Playwright — the server is rate-limiting us, not saying the link is broken.
Respect `Retry-After` if present: pause that host's gate before the next request.

**Transient retry:** retry once on connection errors (`ConnectError`,
`TimeoutError`) before recording a failure. 4xx/5xx are definitive and not
retried.

**Error field format:** a short prefix makes errors queryable without a separate
column: `ssl:`, `dns:`, `timeout:`, `connect:`, `http:NNN`, `playwright:`.
Free-text detail follows.

**Playwright errors:** strip the multi-line ANSI call log Playwright appends to
error messages so rows stay single-line.

**Bypass hosts:** a configurable set of hosts that are never contacted (empty by
default). Rows for bypass hosts are written immediately as broken.

### Concurrency

- Workers: `asyncio.Semaphore(workers)` limits how many URLs are in flight at once
- Playwright: separate `asyncio.Semaphore(pw_pages)` (one browser, many contexts)
- Rate gate: one lock + timestamp per host. **Every outbound request — HEAD, GET,
  or Playwright — acquires the gate before firing.** This is the only per-host
  rate control. A URL that goes through all three stages sends three requests to
  that host, each at least `interval_ms` apart.
- DB writes: a single writer coroutine reads from a queue — one connection, no
  contention

### CLI

```
python -m scripts.check_links [options]

  --limit N        only check the first N unchecked URLs
  --only-host D    restrict to URLs on host D or its subdomains
  --workers N      URLs in flight at once (default 100)
  --pw-pages N     max concurrent Playwright pages (default 40)
  --timeout-ms N   HTTP timeout per request (default 15000)
  --interval-ms N  gap between requests per host (default 500 = 2 req/s)
  --force          recheck URLs already in link_check_results
  --help
```

### Resuming

`load_urls` queries:

```sql
SELECT DISTINCT l.url
FROM links l
LEFT JOIN link_check_results lcr ON l.url = lcr.url
WHERE lcr.url IS NULL       -- skip already checked (omitted with --force)
  AND l.url IS NOT NULL
  AND l.url != ''
  AND l.url LIKE 'http%'
ORDER BY l.url
```

Results are upserted as each URL finishes, so interrupting loses at most the
URLs currently in flight.

---

## Tests

- `is_checkable_url`: unit tests, no mocks (valid http/https, blank, unparseable, ftp, mailto)
- `check_url`: inject `AsyncMock` for `fetch_fn` and `pw_fn`; test each branch
- `load_urls` / `write_result`: pass a mock `db`; no global state to worry about
- No side effects at import time (no DB connection, no browser launch)

Cases:
- HEAD 200 → ok, method=HEAD
- HEAD 404 → broken, GET not called
- HEAD timeout → Playwright called, GET not called
- HEAD error → GET called, GET 200 → ok, method=GET
- GET 404 → broken, Playwright not called
- GET error → Playwright called
- Playwright ok → ok, method=PLAYWRIGHT
- Playwright download → ok, method=PLAYWRIGHT
- Playwright error → broken, error captured

---

## Files

| File | Change |
|---|---|
| `explorer/migrations/0016_link_check_results.py` | new |
| `explorer/models.py` | add `LinkCheckResult` model |
| `scripts/check_links.py` | new |
| `tests/test_check_links.py` | new |
| `justfile` | add `check-links` recipe |
| `pyproject.toml` | add `httpx` and `playwright` if not present |

Justfile recipe:

```just
check-links *args:
    uv run --env-file .env python -m scripts.check_links {{args}}
```

---

## Progress page

A standalone page at `/check-progress` showing live stats while the checker
runs. A small JS snippet polls a JSON endpoint every 3 seconds and rewrites
the table in place.

### JSON endpoint — `GET /check-progress/data`

Returns overall totals and a row per host:

```json
{
  "total": 120000,
  "checked": 45000,
  "ok": 38000,
  "broken": 7000,
  "hosts": [
    {
      "host": "data.gov.uk",
      "total": 4200,
      "checked": 1800,
      "ok": 1650,
      "broken": 150,
      "errors": {
        "ssl": 12, "dns": 8, "timeout": 45,
        "connect": 30, "http": 42, "playwright": 13
      }
    },
    ...
  ]
}
```

`hosts` is sorted by `total` descending. `total` is distinct URLs for that host
(matching what the checker actually processes). Unchecked hosts still appear —
`checked` is 0.

SQL for the endpoint:

```sql
SELECT
    l.host,
    COUNT(DISTINCT l.url)                                        AS total,
    COUNT(lcr.url)                                               AS checked,
    COUNT(lcr.url) FILTER (WHERE lcr.ok)                        AS ok,
    COUNT(lcr.url) FILTER (WHERE lcr.ok = false)                AS broken,
    COUNT(lcr.url) FILTER (WHERE lcr.error LIKE 'ssl:%')        AS err_ssl,
    COUNT(lcr.url) FILTER (WHERE lcr.error LIKE 'dns:%')        AS err_dns,
    COUNT(lcr.url) FILTER (WHERE lcr.error LIKE 'timeout:%')    AS err_timeout,
    COUNT(lcr.url) FILTER (WHERE lcr.error LIKE 'connect:%')    AS err_connect,
    COUNT(lcr.url) FILTER (WHERE lcr.error LIKE 'http:%')       AS err_http,
    COUNT(lcr.url) FILTER (WHERE lcr.error LIKE 'playwright:%') AS err_playwright
FROM links l
LEFT JOIN link_check_results lcr ON l.url = lcr.url
GROUP BY l.host
ORDER BY total DESC
```

### Page — `GET /check-progress`

Renders a shell template. JS takes over from there.

Layout:
- Summary bar: total URLs / checked / ok / broken / % complete
- Table: one row per host, columns: host · total · checked · ok · broken ·
  error breakdown (ssl / dns / timeout / connect / http / playwright)
- Rows with `checked = 0` shown greyed out at the bottom
- Polling stops automatically once `checked = total`

### Files

| File | Change |
|---|---|
| `explorer/views/check_progress.py` | new — page view + JSON view |
| `explorer/templates/check_progress.html` | new |
| `explorer/queries/check_progress.py` | new — SQL query |
| `config/urls.py` | add `/check-progress` and `/check-progress/data` routes |

---

## Deferred

- Bypass hosts: start empty, add as needed
- `--force` by age (`checked_at < now - 30d`) rather than all-or-nothing
- Result history (currently upsert overwrites; no audit log)

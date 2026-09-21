"""Link checker — HEAD → GET → Playwright fallback.

Reads all distinct unchecked URLs from the `links` table, checks each
one, and upserts results into `link_check_results`. Resumable: already-
checked URLs are skipped unless --force is given. Safe to interrupt and
rerun.

Usage:
    python -m scripts.check_links [options]
    just check-links [options]
"""

import asyncio
import re
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from itertools import chain, zip_longest
from typing import Any
from urllib.parse import urlparse

import httpx
import typer

try:
    from playwright.async_api import async_playwright as _async_playwright

    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False

from scripts.db import Db, connect, database_url

BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
BROWSER_HEADERS = {"User-Agent": BROWSER_UA, "Accept": "*/*"}

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mK]")
_CALL_LOG_RE = re.compile(r"\n?=+\s*logs\s*=+.*$", re.DOTALL | re.IGNORECASE)

app = typer.Typer(add_completion=False)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def is_checkable_url(url: str | None) -> bool:
    """Return True for http/https URLs that look valid enough to attempt."""
    if not url or not url.strip():
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _strip_pw_error(msg: str) -> str:
    """Strip ANSI codes and Playwright call-log appendix from an error message."""
    msg = _ANSI_RE.sub("", msg)
    msg = _CALL_LOG_RE.sub("", msg)
    return msg.strip()


def _classify_connect_error(exc: httpx.ConnectError) -> str:
    msg = str(exc).lower()
    if "ssl" in msg or "certificate" in msg or "handshake" in msg:
        return f"ssl:{exc}"
    if "getaddrinfo" in msg or "name or service not known" in msg or "nodename nor servname" in msg:
        return f"dns:{exc}"
    return f"connect:{exc}"


# ---------------------------------------------------------------------------
# Per-host rate gate (asyncio)
# ---------------------------------------------------------------------------


class HostGate:
    """Per-host rate limiter with dead-host detection.

    Rate logic:
      - success (any 2xx–4xx except 429): count streak; every SPEED_UP_AFTER
        consecutive successes steps the interval down by floor_ms toward floor_ms.
      - 429: permanently lock acceleration; step interval up by floor_ms toward start_ms.
      - 5xx / timeout / connect error: count toward DEAD_THRESHOLD; no rate change.

    Dead-host logic:
      - Once a host accumulates DEAD_THRESHOLD dead signals, is_dead() returns True
        and record() returns True exactly once (the turn it crosses the threshold).
    """

    SPEED_UP_AFTER = 5
    DEAD_THRESHOLD = 10

    def __init__(self, start_ms: int = 1000, floor_ms: int = 250) -> None:
        self._start = start_ms / 1000.0
        self._floor = floor_ms / 1000.0
        self._step = floor_ms / 1000.0
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}
        self._intervals: dict[str, float] = {}
        self._streak: dict[str, int] = {}
        self._accelerating: dict[str, bool] = {}
        self._dead_counts: dict[str, int] = {}
        self._dead: set[str] = set()

    def _cur_interval(self, host: str) -> float:
        return self._intervals.get(host, self._start)

    async def acquire(self, host: str) -> None:
        if host not in self._locks:
            self._locks[host] = asyncio.Lock()
            self._last[host] = 0.0
        async with self._locks[host]:
            now = time.monotonic()
            wait = self._last[host] + self._cur_interval(host) - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last[host] = time.monotonic()

    def record(self, host: str, *, status: int | None, error: str | None) -> bool:
        """Update per-host state. Returns True if the host just crossed the dead threshold."""
        err = error or ""
        is_success = status is not None and status != 429 and status < 500
        is_429 = status == 429
        is_dead_signal = (
            (status is not None and status >= 500)
            or err.startswith("timeout:")
            or err.startswith("connect:")
            or err.startswith("dns:")
            or err.startswith("ssl:")
            or (err.startswith("playwright:") and err != "playwright:unavailable")
        )

        if is_success:
            if self._accelerating.get(host, True):
                streak = self._streak.get(host, 0) + 1
                self._streak[host] = streak
                if streak >= self.SPEED_UP_AFTER:
                    self._intervals[host] = max(self._cur_interval(host) - self._step, self._floor)
                    self._streak[host] = 0
        elif is_429:
            self._accelerating[host] = False
            self._streak[host] = 0
            self._intervals[host] = min(self._cur_interval(host) + self._step, self._start)
        elif is_dead_signal:
            self._streak[host] = 0
            count = self._dead_counts.get(host, 0) + 1
            self._dead_counts[host] = count
            if count >= self.DEAD_THRESHOLD and host not in self._dead:
                self._dead.add(host)
                return True

        return False

    def is_dead(self, host: str) -> bool:
        return host in self._dead


# ---------------------------------------------------------------------------
# check_url — HEAD → GET → Playwright chain
# ---------------------------------------------------------------------------


def _make_result(
    url: str,
    *,
    method: str,
    ok: bool,
    status: int | None = None,
    final_url: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "url": url,
        "checked_at": datetime.now(tz=UTC).isoformat(),
        "method": method,
        "ok": ok,
        "http_status": status,
        "final_url": final_url,
        "error": error,
    }


async def check_url(
    url: str,
    *,
    fetch_fn: Callable,
    pw_fn: Callable | None = None,
    gate: HostGate | None = None,
    pw_sem: asyncio.Semaphore | None = None,
    timeout_ms: int = 15_000,
    bypass_hosts: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Check one URL using the HEAD → GET → Playwright chain.

    fetch_fn(method, url) and pw_fn(url) are injected so tests can mock them.
    gate and pw_sem are optional; when absent their acquisition is skipped.
    """
    host = urlparse(url).hostname or ""

    if host in bypass_hosts:
        return _make_result(url, method="SKIPPED", ok=False, error="connect:bypass host")

    timeout_s = timeout_ms / 1000.0

    async def _fetch(method: str) -> httpx.Response:
        if gate:
            await gate.acquire(host)
        return await fetch_fn(method, url)

    # --- HEAD ---
    head_status: int | None = None
    head_final: str | None = None
    need_get = False
    need_pw = False

    for _attempt in range(2):
        try:
            resp = await _fetch("HEAD")
            head_status = resp.status_code
            head_final = str(resp.url)
            break
        except httpx.TimeoutException:
            # timeout: skip GET, go straight to Playwright
            need_pw = True
            break
        except httpx.ConnectError:
            if _attempt == 0:
                await asyncio.sleep(1)
                continue
            # connect error: fall through to GET
            need_get = True
            break
        except httpx.HTTPStatusError:
            break
        except httpx.HTTPError:
            if _attempt == 0:
                await asyncio.sleep(1)
                continue
            # other HTTP error: fall through to GET
            need_get = True
            break

    if head_status is not None and not need_pw:
        if 200 <= head_status < 400:
            return _make_result(url, method="HEAD", ok=True, status=head_status, final_url=head_final)
        if head_status == 429:
            return _make_result(url, method="HEAD", ok=False, status=429)
        if head_status in (404, 410):
            return _make_result(url, method="HEAD", ok=False, status=head_status)
        need_get = True

    # --- GET ---
    if need_get or (head_status is None and not need_pw):
        get_status: int | None = None
        get_final: str | None = None

        for _attempt in range(2):
            try:
                resp = await _fetch("GET")
                get_status = resp.status_code
                get_final = str(resp.url)
                break
            except httpx.TimeoutException:
                # timeout on GET: broken, skip Playwright
                return _make_result(url, method="GET", ok=False, error=f"timeout:{timeout_s}s")
            except httpx.ConnectError:
                if _attempt == 0:
                    await asyncio.sleep(1)
                    continue
                # connect error on GET: fall through to Playwright (get_status stays None)
                break
            except httpx.HTTPError:
                if _attempt == 0:
                    await asyncio.sleep(1)
                    continue
                # other HTTP error on GET: fall through to Playwright
                break

        if get_status is not None:
            if 200 <= get_status < 400:
                return _make_result(url, method="GET", ok=True, status=get_status, final_url=get_final)
            if get_status == 429:
                return _make_result(url, method="GET", ok=False, status=429)
            if get_status in (404, 410):
                return _make_result(url, method="GET", ok=False, status=get_status)
            need_pw = True
        else:
            need_pw = True

    # --- Playwright ---
    if not need_pw or pw_fn is None:
        status = head_status if head_status is not None else None
        return _make_result(url, method="ERROR", ok=False, status=status, error="playwright:unavailable")

    if pw_sem:
        async with pw_sem:
            if gate:
                await gate.acquire(host)
            pw_result = await pw_fn(url)
    else:
        if gate:
            await gate.acquire(host)
        pw_result = await pw_fn(url)

    if pw_result.get("ok"):
        return _make_result(
            url,
            method="PLAYWRIGHT",
            ok=True,
            status=pw_result.get("status"),
            final_url=pw_result.get("final_url"),
        )
    return _make_result(
        url,
        method="PLAYWRIGHT",
        ok=False,
        status=pw_result.get("status"),
        error=pw_result.get("error"),
    )


# ---------------------------------------------------------------------------
# Playwright helper (constructed in main, not imported at module level)
# ---------------------------------------------------------------------------


async def make_pw_fn(browser: Any, timeout_ms: int) -> Callable:
    """Return a coroutine that navigates to url using a fresh browser context."""

    async def pw_check(url: str) -> dict[str, Any]:
        ctx = await browser.new_context()
        try:
            page = await ctx.new_page()
            try:
                response = await page.goto(url, timeout=timeout_ms, wait_until="load")
                final = page.url
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                if "download" in msg.lower():
                    return {"ok": True, "status": None, "final_url": url}
                clean = _strip_pw_error(msg)[:300]
                return {"ok": False, "status": None, "error": f"playwright:{clean}"}
            else:
                if response is None:
                    return {"ok": True, "status": None, "final_url": final}
                status = response.status
                return {"ok": status < 400, "status": status, "final_url": final}
            finally:
                await page.close()
        finally:
            await ctx.close()

    return pw_check


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

_POPULATE_SQL = """
INSERT INTO link_check_results (link_id, url)
SELECT id, url FROM links
ON CONFLICT (link_id) DO NOTHING
"""

_CARRY_OVER_SQL = """
UPDATE link_check_results AS target
SET checked_at  = source.checked_at,
    method      = source.method,
    ok          = source.ok,
    http_status = source.http_status,
    final_url   = source.final_url,
    error       = source.error
FROM (
    SELECT DISTINCT ON (url)
           url, checked_at, method, ok, http_status, final_url, error
    FROM link_check_results
    WHERE checked_at IS NOT NULL
    ORDER BY url, checked_at DESC
) source
WHERE source.url = target.url
  AND target.checked_at IS NULL
"""

_DELETE_ORPHANS_SQL = """
DELETE FROM link_check_results
WHERE link_id NOT IN (SELECT id FROM links)
"""

_UPDATE_BY_URL_SQL = """
UPDATE link_check_results
SET checked_at  = ?,
    method      = ?,
    ok          = ?,
    http_status = ?,
    final_url   = ?,
    error       = ?
WHERE url = ?
"""

_LOAD_SQL = """
SELECT DISTINCT url
FROM link_check_results
WHERE url IS NOT NULL
  AND url LIKE 'http%%'
  AND checked_at IS NULL
  {extra}
ORDER BY url
"""

_LOAD_FORCE_SQL = """
SELECT DISTINCT url
FROM link_check_results
WHERE url IS NOT NULL
  AND url LIKE 'http%%'
  {extra}
ORDER BY url
"""


def _interleave_by_host(urls: list[str]) -> list[str]:
    """Round-robin interleave URLs across hosts, shuffled within each host group."""
    by_host: dict[str, list[str]] = defaultdict(list)
    for url in urls:
        by_host[urlparse(url).hostname or ""].append(url)
    groups = list(by_host.values())
    return [u for u in chain.from_iterable(zip_longest(*groups)) if u is not None]


def load_urls(
    db: Db,
    *,
    force: bool = False,
    limit: int | None = None,
    only_host: str | None = None,
) -> list[str]:
    """Return unchecked (or all, with --force) http URLs from link_check_results."""
    clauses = []
    params: list[Any] = []

    if only_host:
        clauses.append("AND (split_part(url, '/', 3) = ? OR split_part(url, '/', 3) LIKE ?)")
        params.extend([only_host, f"%.{only_host}"])

    extra = "\n  ".join(clauses)
    template = _LOAD_FORCE_SQL if force else _LOAD_SQL
    sql = template.format(extra=extra)

    rows = db.prepare(sql).all(*params)
    urls = [r["url"] for r in rows if is_checkable_url(r["url"])]
    urls = _interleave_by_host(urls)
    if limit:
        urls = urls[:limit]
    return urls


def write_result(db: Db, result: dict[str, Any]) -> None:
    stmt = db.prepare(_UPDATE_BY_URL_SQL)
    stmt.run(
        result["checked_at"],
        result["method"],
        result["ok"],
        result["http_status"],
        result["final_url"],
        result["error"],
        result["url"],
    )


_MARK_BLANK_SQL = """
UPDATE link_check_results
SET checked_at  = %s,
    method      = 'SKIPPED',
    ok          = false,
    http_status = NULL,
    final_url   = NULL,
    error       = 'url:blank'
WHERE url IS NULL OR url = ''
"""

_MARK_MALFORMED_SQL = """
UPDATE link_check_results
SET checked_at  = %s,
    method      = 'SKIPPED',
    ok          = false,
    http_status = NULL,
    final_url   = NULL,
    error       = 'url:malformed'
WHERE link_id IN (
    SELECT id FROM links
    WHERE host IS NULL AND url IS NOT NULL AND url != ''
)
"""

# Catches anything that slips past the blank/malformed marks but can't be
# HTTP-checked: typo schemes (htts://, hhttps://, ttp://), non-HTTP schemes
# (ftp://, file://), wrong case (Https://), and http-prefixed-but-malformed
# (http:/foo, https:///foo). Condition mirrors _LOAD_SQL's LIKE filter plus
# the is_checkable_url netloc requirement.
_MARK_UNCHECKABLE_SQL = """
UPDATE link_check_results
SET checked_at  = %s,
    method      = 'SKIPPED',
    ok          = false,
    http_status = NULL,
    final_url   = NULL,
    error       = 'url:malformed'
WHERE checked_at IS NULL
  AND url IS NOT NULL AND url != ''
  AND NOT (url LIKE 'http%%' AND url ~* '^https?://[^/]')
"""


def _populate_link_check_results(db: Db) -> int:
    """Insert a pending row for every link not yet in link_check_results. Returns count inserted."""
    with db.conn.cursor() as cur:
        cur.execute(_POPULATE_SQL)
        return cur.rowcount


def _carry_over_check_results(db: Db) -> int:
    """Copy check results from old (orphaned) rows to new rows by URL match.

    After a rebuild, old rows have stale link_ids but valid check data.
    New rows (from populate) have correct link_ids but NULL checked_at.
    This copies the most recent result for each URL to fill in the gaps.
    """
    with db.conn.cursor() as cur:
        cur.execute(_CARRY_OVER_SQL)
        return cur.rowcount


def _delete_orphan_rows(db: Db) -> int:
    """Delete link_check_results rows whose link_id is no longer in links."""
    with db.conn.cursor() as cur:
        cur.execute(_DELETE_ORPHANS_SQL)
        return cur.rowcount


def _mark_blank_url_links(db: Db) -> int:
    """Mark links with no URL as url:blank. Returns count marked."""
    now = datetime.now(tz=UTC).isoformat()
    with db.conn.cursor() as cur:
        cur.execute(_MARK_BLANK_SQL, (now,))
        return cur.rowcount


def _mark_malformed_urls(db: Db) -> int:
    """Mark links with unparseable URLs (host IS NULL) as url:malformed. Returns count marked."""
    now = datetime.now(tz=UTC).isoformat()
    with db.conn.cursor() as cur:
        cur.execute(_MARK_MALFORMED_SQL, (now,))
        return cur.rowcount


def _mark_uncheckable_urls(db: Db) -> int:
    """Mark non-HTTP/non-checkable URLs (typo schemes, ftp://, etc.) as url:malformed."""
    now = datetime.now(tz=UTC).isoformat()
    with db.conn.cursor() as cur:
        cur.execute(_MARK_UNCHECKABLE_SQL, (now,))
        return cur.rowcount


_DEAD_HOST_SQL = """
UPDATE link_check_results
SET checked_at  = %s,
    method      = 'SKIPPED',
    ok          = false,
    http_status = NULL,
    final_url   = NULL,
    error       = 'timeout:dead host'
WHERE link_id IN (SELECT id FROM links WHERE host = %s)
  AND checked_at IS NULL
"""


def _bulk_mark_dead_host(db: Db, host: str) -> int:
    """Mark all remaining unchecked URLs for host as timed-out. Returns count marked."""
    now = datetime.now(tz=UTC).isoformat()
    with db.conn.cursor() as cur:
        cur.execute(_DEAD_HOST_SQL, (now, host))
        return cur.rowcount


# ---------------------------------------------------------------------------
# Writer coroutine (single consumer, no lock contention on DB)
# ---------------------------------------------------------------------------


async def writer(queue: asyncio.Queue, db: Db) -> None:
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            break
        write_result(db, item)
        queue.task_done()


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


async def _process_url(
    url: str,
    *,
    fetch_fn: Callable,
    pw_fn: Callable | None,
    gate: HostGate,
    pw_sem: asyncio.Semaphore,
    worker_sem: asyncio.Semaphore,
    timeout_ms: int,
    queue: asyncio.Queue,
    counter: list[int],
    db: Db,
) -> None:
    host = urlparse(url).hostname or ""

    async with worker_sem:
        if gate.is_dead(host):
            counter[0] += 1
            return

        try:
            result = await check_url(
                url,
                fetch_fn=fetch_fn,
                pw_fn=pw_fn,
                gate=gate,
                pw_sem=pw_sem,
                timeout_ms=timeout_ms,
            )
            newly_dead = gate.record(host, status=result.get("http_status"), error=result.get("error"))
            if newly_dead:
                n = _bulk_mark_dead_host(db, host)
                print(f"  Dead host {host}: marked {n} remaining URL(s) as timed-out", flush=True)
        except Exception as exc:  # noqa: BLE001
            result = _make_result(url, method="ERROR", ok=False, error=f"connect:{exc}")
        await queue.put(result)
        counter[0] += 1


# ---------------------------------------------------------------------------
# Progress logger
# ---------------------------------------------------------------------------


async def _log_progress(
    counter: list[int],
    total: int,
    worker_sem: asyncio.Semaphore,
    pw_sem: asyncio.Semaphore,
    workers: int,
    pw_pages: int,
    queue: asyncio.Queue,
    interval: int = 30,
) -> None:
    last_n = 0
    while True:
        await asyncio.sleep(interval)
        n = counter[0]
        rate = (n - last_n) / interval
        last_n = n
        pct = n * 100 // total if total else 0
        w_used = workers - worker_sem._value
        pw_used = pw_pages - pw_sem._value
        q_depth = queue.qsize()
        print(
            f"  {n}/{total} ({pct}%) | {rate:.1f}/s"
            f" | workers {w_used}/{workers} | playwright {pw_used}/{pw_pages}"
            f" | queue {q_depth}",
            flush=True,
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


@app.command()
def main(
    limit: int = typer.Option(0, help="Only check the first N unchecked URLs (0 = all)"),
    only_host: str = typer.Option("", help="Restrict to URLs on this host or its subdomains"),
    workers: int = typer.Option(200, help="URLs in flight at once"),
    pw_pages: int = typer.Option(70, help="Max concurrent Playwright pages"),
    timeout_ms: int = typer.Option(15_000, help="HTTP timeout per request (ms)"),
    start_ms: int = typer.Option(1_000, help="Starting gap per host in ms (1 req/s); speeds up toward --floor-ms"),
    floor_ms: int = typer.Option(250, help="Minimum gap per host in ms (4 req/s)"),
    force: bool = typer.Option(False, help="Recheck URLs already in link_check_results"),
) -> None:
    asyncio.run(
        _main(
            limit=limit or None,
            only_host=only_host or None,
            workers=workers,
            pw_pages=pw_pages,
            timeout_ms=timeout_ms,
            start_ms=start_ms,
            floor_ms=floor_ms,
            force=force,
        ),
    )


async def _main(
    *,
    limit: int | None,
    only_host: str | None,
    workers: int,
    pw_pages: int,
    timeout_ms: int,
    start_ms: int,
    floor_ms: int,
    force: bool,
) -> None:
    db = connect(database_url())
    try:
        n_new = _populate_link_check_results(db)
        if n_new:
            print(f"  Added {n_new} new pending row(s) to link_check_results", flush=True)

        n_carried = _carry_over_check_results(db)
        if n_carried:
            print(f"  Carried over {n_carried} check result(s) by URL match", flush=True)

        n_deleted = _delete_orphan_rows(db)
        if n_deleted:
            print(f"  Deleted {n_deleted} orphaned row(s) from link_check_results", flush=True)

        n_blank = _mark_blank_url_links(db)
        if n_blank:
            print(f"  Marked {n_blank} blank URL link(s) as url:blank", flush=True)

        n_malformed = _mark_malformed_urls(db)
        if n_malformed:
            print(f"  Marked {n_malformed} malformed URL(s) as url:malformed", flush=True)

        n_uncheckable = _mark_uncheckable_urls(db)
        if n_uncheckable:
            print(f"  Marked {n_uncheckable} uncheckable URL(s) as url:malformed", flush=True)

        print("Loading URLs…", flush=True)
        urls = load_urls(db, force=force, limit=limit, only_host=only_host)
        total = len(urls)
        print(f"  {total} URL(s) to check", flush=True)
        if not total:
            return

        if not _HAS_PLAYWRIGHT:
            print("  playwright not installed — Playwright fallback disabled", flush=True)

        gate = HostGate(start_ms, floor_ms)
        worker_sem = asyncio.Semaphore(workers)
        pw_sem = asyncio.Semaphore(pw_pages)
        queue: asyncio.Queue[dict | None] = asyncio.Queue()
        counter: list[int] = [0]

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout_ms / 1000.0,
            headers=BROWSER_HEADERS,
            verify=True,
        ) as client:

            async def fetch_fn(method: str, url: str) -> httpx.Response:
                return await client.request(method, url)

            if _HAS_PLAYWRIGHT:
                try:
                    async with _async_playwright() as pw:
                        browser = await pw.chromium.launch(headless=True)
                        pw_fn = await make_pw_fn(browser, timeout_ms)
                        await _run_workers(
                            urls,
                            fetch_fn=fetch_fn,
                            pw_fn=pw_fn,
                            gate=gate,
                            pw_sem=pw_sem,
                            worker_sem=worker_sem,
                            timeout_ms=timeout_ms,
                            queue=queue,
                            db=db,
                            counter=counter,
                            total=total,
                            workers=workers,
                            pw_pages=pw_pages,
                        )
                        await browser.close()
                except Exception as exc:  # noqa: BLE001
                    print(f"  Playwright browser unavailable ({exc}) — falling back to HTTP only", flush=True)
                    await _run_workers(
                        urls,
                        fetch_fn=fetch_fn,
                        pw_fn=None,
                        gate=gate,
                        pw_sem=pw_sem,
                        worker_sem=worker_sem,
                        timeout_ms=timeout_ms,
                        queue=queue,
                        db=db,
                        counter=counter,
                        total=total,
                        workers=workers,
                        pw_pages=pw_pages,
                    )
            else:
                await _run_workers(
                    urls,
                    fetch_fn=fetch_fn,
                    pw_fn=None,
                    gate=gate,
                    pw_sem=pw_sem,
                    worker_sem=worker_sem,
                    timeout_ms=timeout_ms,
                    queue=queue,
                    db=db,
                    counter=counter,
                    total=total,
                    workers=workers,
                    pw_pages=pw_pages,
                )

        print(f"Done: {counter[0]}/{total} URL(s) checked.", flush=True)
    finally:
        db.close()


async def _run_workers(
    urls: list[str],
    *,
    fetch_fn: Callable,
    pw_fn: Callable | None,
    gate: HostGate,
    pw_sem: asyncio.Semaphore,
    worker_sem: asyncio.Semaphore,
    timeout_ms: int,
    queue: asyncio.Queue,
    db: Db,
    counter: list[int],
    total: int,
    workers: int,
    pw_pages: int,
) -> None:
    writer_task = asyncio.create_task(writer(queue, db))
    logger_task = asyncio.create_task(_log_progress(counter, total, worker_sem, pw_sem, workers, pw_pages, queue))

    tasks = [
        asyncio.create_task(
            _process_url(
                url,
                fetch_fn=fetch_fn,
                pw_fn=pw_fn,
                gate=gate,
                pw_sem=pw_sem,
                worker_sem=worker_sem,
                timeout_ms=timeout_ms,
                queue=queue,
                counter=counter,
                db=db,
            ),
        )
        for url in urls
    ]

    await asyncio.gather(*tasks)
    await queue.put(None)
    await writer_task
    logger_task.cancel()


if __name__ == "__main__":
    try:
        app()
    except (RuntimeError, OSError, KeyError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

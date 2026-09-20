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
from collections.abc import Callable
from datetime import UTC, datetime
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

BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
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
    """Asyncio-based per-host rate limiter.

    Every outbound request (HEAD, GET, or Playwright navigation) must call
    acquire(host) before firing; successive requests to the same host are
    separated by at least interval_ms milliseconds.
    """

    def __init__(self, interval_ms: int) -> None:
        self._interval = interval_ms / 1000.0
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}

    async def acquire(self, host: str) -> None:
        if host not in self._locks:
            self._locks[host] = asyncio.Lock()
            self._last[host] = 0.0
        async with self._locks[host]:
            now = time.monotonic()
            wait = self._last[host] + self._interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last[host] = time.monotonic()

    def delay(self, host: str, extra_seconds: float) -> None:
        """Push the next allowed request for host forward by extra_seconds (429 backoff)."""
        self._last[host] = time.monotonic() + extra_seconds


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

_UPSERT_SQL = """
INSERT INTO link_check_results (url, checked_at, method, ok, http_status, final_url, error)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (url) DO UPDATE SET
    checked_at  = EXCLUDED.checked_at,
    method      = EXCLUDED.method,
    ok          = EXCLUDED.ok,
    http_status = EXCLUDED.http_status,
    final_url   = EXCLUDED.final_url,
    error       = EXCLUDED.error
"""

_LOAD_SQL = """
SELECT DISTINCT l.url
FROM links l
LEFT JOIN link_check_results lcr ON l.url = lcr.url
WHERE l.url IS NOT NULL
  AND l.url != ''
  AND l.url LIKE 'http%%'
  {extra}
ORDER BY l.url
"""

_LOAD_FORCE_SQL = """
SELECT DISTINCT l.url
FROM links l
WHERE l.url IS NOT NULL
  AND l.url != ''
  AND l.url LIKE 'http%%'
  {extra}
ORDER BY l.url
"""


def load_urls(
    db: Db,
    *,
    force: bool = False,
    limit: int | None = None,
    only_host: str | None = None,
) -> list[str]:
    """Return unchecked (or all, with --force) valid URLs from the links table."""
    clauses = []
    params: list[Any] = []

    if not force:
        clauses.append("AND lcr.url IS NULL")

    if only_host:
        clauses.append("AND (l.host = ? OR l.host LIKE ?)")
        params.extend([only_host, f"%.{only_host}"])

    extra = "\n  ".join(clauses)
    template = _LOAD_FORCE_SQL if force else _LOAD_SQL
    sql = template.format(extra=extra)

    if limit:
        sql += f" LIMIT {limit}"

    rows = db.prepare(sql).all(*params)
    return [r["url"] for r in rows if is_checkable_url(r["url"])]


def write_result(db: Db, result: dict[str, Any]) -> None:
    stmt = db.prepare(_UPSERT_SQL)
    stmt.run(
        result["url"],
        result["checked_at"],
        result["method"],
        result["ok"],
        result["http_status"],
        result["final_url"],
        result["error"],
    )


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
    bypass_hosts: frozenset[str],
    queue: asyncio.Queue,
    counter: list[int],
) -> None:
    async with worker_sem:
        try:
            result = await check_url(
                url,
                fetch_fn=fetch_fn,
                pw_fn=pw_fn,
                gate=gate,
                pw_sem=pw_sem,
                timeout_ms=timeout_ms,
                bypass_hosts=bypass_hosts,
            )
            # Respect Retry-After for 429 responses
            if result.get("http_status") == 429:
                host = urlparse(url).hostname or ""
                gate.delay(host, 30.0)
        except Exception as exc:  # noqa: BLE001
            result = _make_result(url, method="ERROR", ok=False, error=f"connect:{exc}")
        await queue.put(result)
        counter[0] += 1


# ---------------------------------------------------------------------------
# Progress logger
# ---------------------------------------------------------------------------


async def _log_progress(counter: list[int], total: int, interval: int = 30) -> None:
    while True:
        await asyncio.sleep(interval)
        n = counter[0]
        pct = n * 100 // total if total else 0
        print(f"  {n}/{total} ({pct}%) checked", flush=True)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


@app.command()
def main(
    limit: int = typer.Option(0, help="Only check the first N unchecked URLs (0 = all)"),
    only_host: str = typer.Option("", help="Restrict to URLs on this host or its subdomains"),
    workers: int = typer.Option(100, help="URLs in flight at once"),
    pw_pages: int = typer.Option(40, help="Max concurrent Playwright pages"),
    timeout_ms: int = typer.Option(15_000, help="HTTP timeout per request (ms)"),
    interval_ms: int = typer.Option(500, help="Gap between requests per host (ms)"),
    force: bool = typer.Option(False, help="Recheck URLs already in link_check_results"),
) -> None:
    asyncio.run(
        _main(
            limit=limit or None,
            only_host=only_host or None,
            workers=workers,
            pw_pages=pw_pages,
            timeout_ms=timeout_ms,
            interval_ms=interval_ms,
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
    interval_ms: int,
    force: bool,
) -> None:
    db = connect(database_url())
    try:
        print("Loading URLs…", flush=True)
        urls = load_urls(db, force=force, limit=limit, only_host=only_host)
        total = len(urls)
        print(f"  {total} URL(s) to check", flush=True)
        if not total:
            return

        if not _HAS_PLAYWRIGHT:
            print("  playwright not installed — Playwright fallback disabled", flush=True)

        gate = HostGate(interval_ms)
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
                async with _async_playwright() as pw:
                    browser = await pw.chromium.launch(headless=True)
                    pw_fn = await make_pw_fn(browser, timeout_ms)
                    await _run_workers(
                        urls, fetch_fn=fetch_fn, pw_fn=pw_fn,
                        gate=gate, pw_sem=pw_sem, worker_sem=worker_sem,
                        timeout_ms=timeout_ms, queue=queue, db=db,
                        counter=counter, total=total,
                    )
                    await browser.close()
            else:
                await _run_workers(
                    urls, fetch_fn=fetch_fn, pw_fn=None,
                    gate=gate, pw_sem=pw_sem, worker_sem=worker_sem,
                    timeout_ms=timeout_ms, queue=queue, db=db,
                    counter=counter, total=total,
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
) -> None:
    bypass: frozenset[str] = frozenset()
    writer_task = asyncio.create_task(writer(queue, db))
    logger_task = asyncio.create_task(_log_progress(counter, total))

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
                bypass_hosts=bypass,
                queue=queue,
                counter=counter,
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

"""Unit tests for scripts/check_links.py (offline — no DB, no network).

Covers is_checkable_url and the check_url HEAD→GET→Playwright chain;
fetch_fn and pw_fn are injected AsyncMocks so no real HTTP or browser
is needed.
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock

import httpx

os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/test-db")

import scripts.check_links as cl

# ---------------------------------------------------------------------------
# is_checkable_url
# ---------------------------------------------------------------------------


def test_is_checkable_url_valid_http():
    assert cl.is_checkable_url("http://example.com/file.csv") is True


def test_is_checkable_url_valid_https():
    assert cl.is_checkable_url("https://data.gov.uk/dataset/abc") is True


def test_is_checkable_url_blank():
    assert cl.is_checkable_url("") is False
    assert cl.is_checkable_url(None) is False
    assert cl.is_checkable_url("   ") is False


def test_is_checkable_url_ftp():
    assert cl.is_checkable_url("ftp://example.com/file") is False


def test_is_checkable_url_mailto():
    assert cl.is_checkable_url("mailto:user@example.com") is False


def test_is_checkable_url_no_host():
    assert cl.is_checkable_url("http://") is False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resp(status: int, url: str = "http://example.com/resource") -> MagicMock:
    """Build a fake httpx.Response-like object."""
    r = MagicMock()
    r.status_code = status
    r.url = url
    return r


def _run(coro):
    return asyncio.run(coro)


URL = "http://example.com/resource"


# ---------------------------------------------------------------------------
# check_url — HEAD branch
# ---------------------------------------------------------------------------


def test_head_200_ok():
    fetch = AsyncMock(return_value=_resp(200))
    result = _run(cl.check_url(URL, fetch_fn=fetch, pw_fn=None))
    assert result["ok"] is True
    assert result["method"] == "HEAD"
    assert result["http_status"] == 200
    assert fetch.call_count == 1
    fetch.assert_called_with("HEAD", URL)


def test_head_301_ok():
    fetch = AsyncMock(return_value=_resp(301, "http://example.com/other"))
    result = _run(cl.check_url(URL, fetch_fn=fetch, pw_fn=None))
    assert result["ok"] is True
    assert result["method"] == "HEAD"


def test_head_404_broken_no_get():
    fetch = AsyncMock(return_value=_resp(404))
    pw = AsyncMock()
    result = _run(cl.check_url(URL, fetch_fn=fetch, pw_fn=pw))
    assert result["ok"] is False
    assert result["method"] == "HEAD"
    assert result["http_status"] == 404
    # GET and Playwright must not be called
    assert fetch.call_count == 1
    pw.assert_not_called()


def test_head_410_broken_no_get():
    fetch = AsyncMock(return_value=_resp(410))
    pw = AsyncMock()
    result = _run(cl.check_url(URL, fetch_fn=fetch, pw_fn=pw))
    assert result["ok"] is False
    assert result["http_status"] == 410
    assert fetch.call_count == 1
    pw.assert_not_called()


def test_head_429_no_fallthrough():
    fetch = AsyncMock(return_value=_resp(429))
    pw = AsyncMock()
    result = _run(cl.check_url(URL, fetch_fn=fetch, pw_fn=pw))
    assert result["ok"] is False
    assert result["http_status"] == 429
    # Playwright must not be called for a 429
    pw.assert_not_called()


def test_head_timeout_skips_get_tries_playwright():
    fetch = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
    pw = AsyncMock(return_value={"ok": True, "status": 200, "final_url": URL})
    result = _run(cl.check_url(URL, fetch_fn=fetch, pw_fn=pw))
    # Playwright was tried, GET was not
    assert result["method"] == "PLAYWRIGHT"
    assert result["ok"] is True
    assert fetch.call_count == 1  # only HEAD, no GET
    pw.assert_called_once_with(URL)


def test_head_500_tries_get():
    fetch = AsyncMock(side_effect=[_resp(500), _resp(200)])
    result = _run(cl.check_url(URL, fetch_fn=fetch, pw_fn=None))
    assert result["ok"] is True
    assert result["method"] == "GET"
    assert fetch.call_count == 2


# ---------------------------------------------------------------------------
# check_url — GET branch
# ---------------------------------------------------------------------------


def test_get_200_ok():
    fetch = AsyncMock(side_effect=[_resp(500), _resp(200)])
    result = _run(cl.check_url(URL, fetch_fn=fetch, pw_fn=None))
    assert result["ok"] is True
    assert result["method"] == "GET"
    assert result["http_status"] == 200


def test_get_404_broken_no_playwright():
    fetch = AsyncMock(side_effect=[_resp(500), _resp(404)])
    pw = AsyncMock()
    result = _run(cl.check_url(URL, fetch_fn=fetch, pw_fn=pw))
    assert result["ok"] is False
    assert result["http_status"] == 404
    pw.assert_not_called()


def test_get_timeout_broken_no_playwright():
    fetch = AsyncMock(side_effect=[_resp(500), httpx.TimeoutException("timed out")])
    pw = AsyncMock()
    result = _run(cl.check_url(URL, fetch_fn=fetch, pw_fn=pw))
    assert result["ok"] is False
    assert "timeout" in result["error"]
    pw.assert_not_called()


def test_get_503_tries_playwright():
    fetch = AsyncMock(side_effect=[_resp(500), _resp(503)])
    pw = AsyncMock(return_value={"ok": True, "status": 200, "final_url": URL})
    result = _run(cl.check_url(URL, fetch_fn=fetch, pw_fn=pw))
    assert result["method"] == "PLAYWRIGHT"
    assert result["ok"] is True
    pw.assert_called_once_with(URL)


# ---------------------------------------------------------------------------
# check_url — Playwright branch
# ---------------------------------------------------------------------------


def test_playwright_ok():
    fetch = AsyncMock(side_effect=httpx.ConnectError("refused"))
    pw = AsyncMock(return_value={"ok": True, "status": 200, "final_url": URL})
    result = _run(cl.check_url(URL, fetch_fn=fetch, pw_fn=pw))
    assert result["method"] == "PLAYWRIGHT"
    assert result["ok"] is True


def test_playwright_download_ok():
    fetch = AsyncMock(side_effect=[_resp(500), _resp(503)])
    pw = AsyncMock(return_value={"ok": True, "status": None, "final_url": URL})
    result = _run(cl.check_url(URL, fetch_fn=fetch, pw_fn=pw))
    assert result["method"] == "PLAYWRIGHT"
    assert result["ok"] is True
    assert result["http_status"] is None


def test_playwright_error_broken():
    fetch = AsyncMock(side_effect=[_resp(500), _resp(503)])
    pw = AsyncMock(return_value={"ok": False, "status": None, "error": "playwright:net::ERR_NAME_NOT_RESOLVED"})
    result = _run(cl.check_url(URL, fetch_fn=fetch, pw_fn=pw))
    assert result["method"] == "PLAYWRIGHT"
    assert result["ok"] is False
    assert "playwright:" in result["error"]


# ---------------------------------------------------------------------------
# load_urls / write_result — mock Db
# ---------------------------------------------------------------------------


def _mock_db(rows: list[dict]):
    """Return a mock Db whose .prepare().all() returns rows."""
    query = MagicMock()
    query.all.return_value = rows
    query.run.return_value = None
    db = MagicMock()
    db.prepare.return_value = query
    return db


def test_load_urls_filters_non_http():
    db = _mock_db([
        {"url": "http://example.com/a"},
        {"url": "ftp://example.com/b"},
        {"url": ""},
        {"url": "https://gov.uk/c"},
    ])
    urls = cl.load_urls(db)
    assert urls == ["http://example.com/a", "https://gov.uk/c"]


def test_load_urls_respects_limit():
    rows = [{"url": f"http://example.com/{i}"} for i in range(10)]
    db = _mock_db(rows)
    cl.load_urls(db, limit=3)
    # limit is applied via SQL, so mock returns all — just check that LIMIT
    # appears in the prepared SQL
    sql_arg = db.prepare.call_args[0][0]
    assert "LIMIT 3" in sql_arg


def test_load_urls_force_omits_join():
    db = _mock_db([{"url": "http://example.com/a"}])
    cl.load_urls(db, force=True)
    sql_arg = db.prepare.call_args[0][0]
    assert "lcr.url IS NULL" not in sql_arg
    assert "link_check_results" not in sql_arg


def test_load_urls_only_host():
    db = _mock_db([{"url": "http://data.gov.uk/a"}])
    cl.load_urls(db, only_host="data.gov.uk")
    sql_arg = db.prepare.call_args[0][0]
    assert "l.host" in sql_arg
    params = db.prepare.return_value.all.call_args[0]
    assert "data.gov.uk" in params
    assert "%.data.gov.uk" in params


def test_write_result_calls_upsert():
    db = _mock_db([])
    result = {
        "url": "http://example.com/a",
        "checked_at": "2026-09-20T12:00:00+00:00",
        "method": "HEAD",
        "ok": True,
        "http_status": 200,
        "final_url": "http://example.com/a",
        "error": None,
    }
    cl.write_result(db, result)
    db.prepare.return_value.run.assert_called_once()
    call_args = db.prepare.return_value.run.call_args[0]
    assert call_args[0] == "http://example.com/a"
    assert call_args[3] is True  # ok
    assert call_args[4] == 200    # http_status


# ---------------------------------------------------------------------------
# _strip_pw_error
# ---------------------------------------------------------------------------


def test_strip_pw_error_removes_ansi():
    msg = "\x1b[31mError\x1b[0m: something"
    assert cl._strip_pw_error(msg) == "Error: something"


def test_strip_pw_error_removes_call_log():
    msg = "Error: net::ERR_NAME_NOT_RESOLVED\n=== logs ===\nnavigating to ...\n============"
    result = cl._strip_pw_error(msg)
    assert "logs" not in result
    assert "Error: net::ERR_NAME_NOT_RESOLVED" in result

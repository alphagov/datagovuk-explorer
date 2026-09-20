"""check-progress query — overall totals and per-host breakdown."""

from django.db import connection

_SQL = """
SELECT
    l.host,
    COUNT(DISTINCT l.url)                                         AS total,
    COUNT(DISTINCT lcr.url)                                                AS checked,
    COUNT(DISTINCT lcr.url) FILTER (WHERE lcr.ok)                         AS ok,
    COUNT(DISTINCT lcr.url) FILTER (WHERE lcr.ok = false)                 AS broken,
    COUNT(DISTINCT lcr.url) FILTER (WHERE lcr.error LIKE 'ssl:%%')        AS err_ssl,
    COUNT(DISTINCT lcr.url) FILTER (WHERE lcr.error LIKE 'dns:%%')        AS err_dns,
    COUNT(DISTINCT lcr.url) FILTER (WHERE lcr.error LIKE 'timeout:%%')    AS err_timeout,
    COUNT(DISTINCT lcr.url) FILTER (WHERE lcr.error LIKE 'connect:%%')    AS err_connect,
    COUNT(DISTINCT lcr.url) FILTER (WHERE lcr.error LIKE 'http:%%')       AS err_http,
    COUNT(DISTINCT lcr.url) FILTER (WHERE lcr.error LIKE 'playwright:%%') AS err_playwright
FROM links l
LEFT JOIN link_check_results lcr ON l.url = lcr.url
GROUP BY l.host
ORDER BY total DESC
"""


def get_check_progress() -> dict:
    """Return overall totals and a per-host breakdown for the progress page."""
    with connection.cursor() as cur:
        cur.execute(_SQL)
        cols = [c.name for c in cur.description]
        rows = [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    total = sum(r["total"] for r in rows)
    checked = sum(r["checked"] for r in rows)
    ok = sum(r["ok"] for r in rows)
    broken = sum(r["broken"] for r in rows)

    hosts = [
        {
            "host": r["host"] or "",
            "total": r["total"],
            "checked": r["checked"],
            "ok": r["ok"],
            "broken": r["broken"],
            "errors": {
                "ssl": r["err_ssl"],
                "dns": r["err_dns"],
                "timeout": r["err_timeout"],
                "connect": r["err_connect"],
                "http": r["err_http"],
                "playwright": r["err_playwright"],
            },
        }
        for r in rows
    ]

    return {
        "total": total,
        "checked": checked,
        "ok": ok,
        "broken": broken,
        "hosts": hosts,
    }

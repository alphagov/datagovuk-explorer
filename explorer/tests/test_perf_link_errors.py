"""Performance timing for GET /links/status.

Opt-in, runs against the live local database:
    just perf explorer/tests/test_perf_link_errors.py

Writes a dated report to docs/perf/YYYY-MM-DD/link_errors.md.
No assertions — this is observation, not a gate.
"""

import time
from datetime import date
from pathlib import Path
from threading import Lock
from unittest.mock import patch

import pytest
from django.test import override_settings

pytestmark = pytest.mark.perf

REPO_ROOT = Path(__file__).parents[2]

CASES = [
    ("baseline", {}),
    ("sort by status desc", {"sort": "status", "dir": "desc"}),
    ("filter by category=NOT_FOUND", {"category": "NOT_FOUND"}),
    ("filter by status=error", {"status": "error"}),
    ("filter by harvested=harvested", {"harvested": "harvested"}),
    ("domains expanded", {"domains": "all"}),
    ("page 2", {"page": "2"}),
]

_results: list[dict] = []


def _clear_caches():
    from explorer.queries.link_errors import link_errors_facet_counts, link_errors_stats

    link_errors_facet_counts.cache_clear()
    link_errors_stats.cache_clear()


# The facet pools run sequentially in the request thread (not fetch_parallel),
# but capture via _fetch_all regardless so every statement is timed.
_extra_queries: list[dict] = []
_extra_lock = Lock()


def _patched_fetch_all(sql, params):
    import explorer.queries.core as _core

    t = time.perf_counter()
    result = _core._real_fetch_all(sql, params)
    ms = (time.perf_counter() - t) * 1000
    with _extra_lock:
        _extra_queries.append({"sql": sql, "time": f"{ms / 1000:.3f}"})
    return result


@pytest.fixture(autouse=True)
def _unblock_live_db(django_db_blocker):
    with django_db_blocker.unblock():
        yield


@pytest.fixture(autouse=True, scope="module")
def _write_report():
    yield
    if not _results:
        return
    out = REPO_ROOT / "docs" / "perf" / str(date.today()) / "link_errors.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# /links/status performance — {date.today()}\n\n"]
    lines.append("| case | wall | render |\n")
    lines.append("|---|---|---|\n")
    for r in _results:
        lines.append(
            f"| {r['label']} | {r['wall_ms']:.0f}ms | {r['render_ms']:.0f}ms |\n",
        )
    lines.append("\n")
    for r in _results:
        lines.append(f"\n## {r['label']}\n")
        lines.append(
            f"wall={r['wall_ms']:.1f}ms  render={r['render_ms']:.1f}ms  ({r['query_count']} queries)\n",
        )
        lines.append("\n| ms | sql |\n|---|---|\n")
        for q in r["queries"]:
            ms = float(q["time"]) * 1000
            raw = q["sql"].replace("\n", " ").replace("|", "\\|")
            sql_preview = raw[:300] + ("..." if len(raw) > 300 else "")
            lines.append(f"| {ms:.1f} | `{sql_preview}` |\n")
    out.write_text("".join(lines))
    print(f"\nreport → {out.relative_to(REPO_ROOT)}")


@pytest.mark.parametrize(("label", "params"), CASES)
@override_settings(DEBUG=True)
def test_link_errors_perf(client, label, params):
    import django.shortcuts

    import explorer.queries.core as _core

    if not hasattr(_core, "_real_fetch_all"):
        _core._real_fetch_all = _core._fetch_all
    if not hasattr(django.shortcuts, "_orig_render"):
        django.shortcuts._orig_render = django.shortcuts.render

    _clear_caches()
    _extra_queries.clear()
    render_ms = 0.0

    def _timed_render(request, template_name, context=None, **kwargs):
        nonlocal render_ms
        t = time.perf_counter()
        result = django.shortcuts._orig_render(request, template_name, context, **kwargs)
        render_ms = (time.perf_counter() - t) * 1000
        return result

    with (
        patch("explorer.queries.core._fetch_all", _patched_fetch_all),
        patch("explorer.views.links_errors.render", _timed_render),
    ):
        t0 = time.perf_counter()
        response = client.get("/links/status", params)
        wall_ms = (time.perf_counter() - t0) * 1000

    assert response.status_code == 200

    all_queries = sorted(_extra_queries, key=lambda q: -float(q["time"]))

    _results.append(
        {
            "label": label,
            "wall_ms": wall_ms,
            "render_ms": render_ms,
            "query_count": len(all_queries),
            "queries": all_queries,
        }
    )

    print(f"\n[{label}]")
    print(f"  wall={wall_ms:.1f}ms  render={render_ms:.1f}ms  ({len(all_queries)} queries)")
    for q in all_queries:
        ms = float(q["time"]) * 1000
        raw = q["sql"].replace("\n", " ")
        sql_preview = raw[:200] + ("..." if len(raw) > 200 else "")
        print(f"    {ms:6.1f}ms  {sql_preview}")

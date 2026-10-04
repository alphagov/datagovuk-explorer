"""Performance timing for GET /organisations.

Opt-in, runs against the live local database (same as `just test-live`):
    just test-live -- explorer/tests/test_perf_organisations.py -s

Writes a dated report to docs/perf/YYYY-MM-DD/organisations.md.
No assertions — this is observation, not a gate.
"""

import time
from datetime import date
from pathlib import Path
from threading import Lock

import pytest
from django.test import override_settings
from unittest.mock import patch

pytestmark = [pytest.mark.live, pytest.mark.perf]

REPO_ROOT = Path(__file__).parents[2]

CASES = [
    ("baseline", {}),
    ("sort by dataset_count desc", {"sort": "dataset_count", "dir": "desc"}),
    ("filter by datasets=0", {"datasets": "0"}),
    ("filter by last_published=never", {"last_published_year": "__none__"}),
    ("page 2", {"page": "2"}),
]

_results: list[dict] = []

_extra_queries: list[dict] = []
_extra_lock = Lock()


def _clear_caches():
    from explorer.queries.organisations import (
        all_org_rows,
        org_aggregate_rows,
        org_created_years,
        org_last_published_years,
        org_link_health_rows,
        organisations_facet_counts,
    )
    all_org_rows.cache_clear()
    org_aggregate_rows.cache_clear()
    org_created_years.cache_clear()
    org_last_published_years.cache_clear()
    org_link_health_rows.cache_clear()
    organisations_facet_counts.cache_clear()


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
    out = REPO_ROOT / "docs" / "perf" / str(date.today()) / "organisations.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# /organisations performance — {date.today()}\n\n"]
    lines.append("| case | wall | render |\n")
    lines.append("|---|---|---|\n")
    for r in _results:
        lines.append(
            f"| {r['label']} "
            f"| {r['wall_ms']:.0f}ms "
            f"| {r['render_ms']:.0f}ms |\n"
        )
    lines.append("\n")
    for r in _results:
        lines.append(f"\n## {r['label']}\n")
        lines.append(
            f"wall={r['wall_ms']:.1f}ms  render={r['render_ms']:.1f}ms  "
            f"({r['query_count']} queries)\n"
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
def test_organisations_perf(client, label, params):
    import explorer.queries.core as _core
    import django.shortcuts

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
        patch("explorer.views.organisations.render", _timed_render),
    ):
        t0 = time.perf_counter()
        response = client.get("/organisations", params)
        wall_ms = (time.perf_counter() - t0) * 1000

    assert response.status_code == 200

    all_queries = sorted(_extra_queries, key=lambda q: -float(q["time"]))

    _results.append({
        "label": label,
        "wall_ms": wall_ms,
        "render_ms": render_ms,
        "query_count": len(all_queries),
        "queries": all_queries,
    })

    print(f"\n[{label}]")
    print(f"  wall={wall_ms:.1f}ms  render={render_ms:.1f}ms  ({len(all_queries)} queries)")
    for q in all_queries:
        ms = float(q["time"]) * 1000
        raw = q["sql"].replace("\n", " ")
        sql_preview = raw[:200] + ("..." if len(raw) > 200 else "")
        print(f"    {ms:6.1f}ms  {sql_preview}")

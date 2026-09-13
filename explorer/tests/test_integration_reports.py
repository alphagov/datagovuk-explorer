"""Integration tests for the data-quality reports against the seeded fixture.

Every report's count/list compiles and agrees, ordering is deterministic, and
the facet counts wire up to the right (sql, params).
"""

import pytest

from explorer.queries.core import Query
from explorer.queries.reports import REPORTS, report_facet_counts, report_stmts

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def test_every_report_count_matches_list():
    for report in REPORTS:
        out = report_stmts(report)
        n = out["count"].get(*out["params"])["n"]
        rows = out["list"].all(*out["params"], 1_000_000, 0)
        assert n == len(rows), f"report {report['key']}: count {n} != list {len(rows)}"
        assert n >= 0


def test_every_report_deterministic_order():
    """Two runs give the same order — the list statements order by `, id`."""
    for report in REPORTS:
        out = report_stmts(report)
        a = [tuple(r.items()) for r in out["list"].all(*out["params"], 500, 0)]
        b = [tuple(r.items()) for r in out["list"].all(*out["params"], 500, 0)]
        assert a == b, f"report {report['key']} order shuffled between runs"


def test_report_facet_counts_shape():
    """Every faceted report's counts_sql compiles; each facet key resolves
    to a (sql, params) pair that executes (wiring/shape, not options)."""
    for report in REPORTS:
        facets = report.get("facets", [])
        if not facets:
            continue
        stmts = report_facet_counts(report, {})
        assert set(stmts) == {f["key"] for f in facets}, report["key"]
        for key, (sql, params) in stmts.items():
            assert isinstance(Query(sql).all(*params), list), f"{report['key']}.{key}"


def test_fixture_populates_every_report_facet():
    """The fixture is sized so every faceted report has options — otherwise
    the report pages would render empty sidebars. A failure here means the
    seed, not the query layer."""
    for report in REPORTS:
        for facet in report.get("facets", []):
            sql, params = report_facet_counts(report, {})[facet["key"]]
            rows = Query(sql).all(*params)
            assert rows, f"fixture has no options for {report['key']}.{facet['key']}"


def test_report_facet_filter_narrows_to_pool():
    """Selecting a facet value filters the report to that value's own pool
    count (self-exclusion lives in the counts; the filter must agree)."""
    for report in REPORTS:
        for facet in report.get("facets", []):
            sql, params = report_facet_counts(report, {})[facet["key"]]
            options = Query(sql).all(*params)
            if not options:
                continue
            top = options[0]
            out = report_stmts(report, {facet["key"]: top["slug"]})
            assert out["count"].get(*out["params"])["n"] == top["count"], (
                f"{report['key']}.{facet['key']}={top['slug']}"
            )

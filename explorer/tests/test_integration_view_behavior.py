"""Page-unique behaviour against the seeded fixture (plan Phase 5, group C).

Everything shared (pager, sub-nav, facet search box, badges, pills) is
unit-tested once via the macros/helpers; the route smoke proves every page
responds. What is left here is the handful of behaviours only one page has:
facet-value validation/fallback, the harvesters facet partition + headline,
and the dataset detail review.
"""

import pytest
from django.test import SimpleTestCase

from explorer.queries.core import Query
from explorer.queries.datasets import datasets_facet_counts, datasets_stmts
from explorer.queries.harvesters import harvest_source_rows, harvest_sources_stmts, harvested_total
from explorer.queries.reports import REPORTS, report_facet_counts, report_stmts
from explorer.views.harvesters import HarvesterFilters, _matches

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

_html_case = SimpleTestCase()


def assert_count(response, n: int, noun: str):
    """The page shows the pagination header count "<n> <noun>"
    (whitespace-insensitive)."""
    assert response.status_code == 200
    _html_case.assertInHTML(f"{n:,} {noun}", response.content.decode())


def _report(key):
    return next(report for report in REPORTS if report["key"] == key)


def _report_count(report, filters=None):
    stmt = report_stmts(report, filters)
    return stmt["count"].get(*stmt["params"])["n"]


def test_report_facet_validation(client):
    """A bogus `?org=` falls back to the unfiltered report; a real value
    filters to the facet pool's own count."""
    report = _report("datasets-no-description")
    sql, params = report_facet_counts(report, {})["org"]
    options = Query(sql).all(*params)
    assert options
    top = options[0]

    unfiltered = _report_count(report)
    filtered = _report_count(report, {"org": top["slug"]})

    assert_count(client.get("/report/datasets-no-description"), unfiltered, "datasets")
    assert_count(client.get("/report/datasets-no-description?org=__bogus__"), unfiltered, "datasets")
    assert_count(client.get(f"/report/datasets-no-description?org={top['slug']}"), filtered, "datasets")
    assert filtered == top["count"]


def test_datasets_bogus_filters_fall_back(client):
    """Unknown `?publisher=` / `?links=` values are ignored (unfiltered),
    while a known publisher narrows to the pool count."""
    unfiltered = _datasets_count({})
    assert_count(client.get("/datasets?publisher=bogus"), unfiltered, "datasets")
    assert_count(client.get("/datasets?links=bogus"), unfiltered, "datasets")
    assert_count(client.get("/datasets?theme=bogus"), unfiltered, "datasets")

    publisher = datasets_facet_counts({})["publishers"][0]["value"]
    assert_count(
        client.get(f"/datasets?publisher={publisher}"),
        _datasets_count({"publisher": publisher}),
        "datasets",
    )


def _datasets_count(filters):
    stmt = datasets_stmts(filters, "organisation", "asc")
    return stmt["count"].get(*stmt["params"])["n"]


def test_harvester_facet_pools_partition_cleared_list():
    """Each /harvesters facet pool counts exactly the rows the SQL list
    count returns with that group's filter cleared (the view's Python
    self-excluding pools and the SQL builder agree)."""
    rows = harvest_source_rows()
    for filters in ({}, {"type": "harvest"}, {"active": "true"}, {"datasets": "0"}):
        active = HarvesterFilters(
            type=filters.get("type"),
            active=filters.get("active"),
            frequency=filters.get("frequency"),
            datasets=filters.get("datasets"),
        )
        for group in ("type", "active", "frequency", "datasets"):
            pool = [r for r in rows if _matches(r, active, exclude=group)]
            cleared = {**filters, group: None}
            stmt = harvest_sources_stmts(cleared, "dataset_count", "desc")
            sql_count = stmt["count"].get(*stmt["params"])["n"]
            assert len(pool) == sql_count, (filters, group)


def test_harvesters_headline_matches_datasets_source_facet():
    """/harvesters' headline "datasets harvested" is the same definition as
    the /datasets SOURCE facet (harvested = 1)."""
    assert harvested_total() == datasets_facet_counts({})["source"]["harvested"]


def test_dataset_detail_renders_review(client):
    """The dataset detail page renders the latest ok review's overall score
    (the fixture holds two for d01; the later one wins)."""
    html = client.get("/dataset/alpha/d01").content.decode()
    assert "Overall 5/5" in html
    assert "LLM review" in html


def test_link_errors_resolved_rows_are_styled(client):
    """OK outcomes render with the distinct resolved treatment (the
    template's category == 'OK' branch; badge/pill markup itself is
    covered by the macro tests)."""
    html = client.get("/links/errors?category=OK").content.decode()
    assert "link-errors-row--ok" in html
    assert "status--ok" in html

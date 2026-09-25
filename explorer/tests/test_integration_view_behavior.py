"""Page-unique behaviour against the seeded fixture.

Everything shared (pager, sub-nav, facet search box, badges, pills) is
unit-tested once via the macros/helpers; the route smoke proves every page
responds. What is left here is the handful of behaviours only one page has:
facet-value validation/fallback, the harvesters facet partition + headline,
and the dataset detail review.
"""

import re

import pytest
from django.test import SimpleTestCase

from explorer.queries.core import Query
from explorer.queries.dashboard import cards
from explorer.queries.datasets import datasets_facet_counts, datasets_stmts
from explorer.queries.harvesters import harvest_source_rows, harvest_sources_stmts, harvested_total
from explorer.queries.reports import (
    REPORTS,
    report_dashboard_count,
    report_facet_counts,
    report_stmts,
    report_unfiltered_count,
)
from explorer.queries.collections import collections_stmts
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


def test_duplicate_content_report_list_and_detail(client):
    """List page: one duplicate-content group — the three fixture datasets
    that share a hash (d01, d05 from alpha, d09 from beta; see root
    conftest.py). Detail page (?hash=): all three members, across orgs."""
    report = _report("datasets-duplicate-content")
    n = _report_count(report)
    assert n == 1  # exactly one duplicate-hash group in the fixture

    assert_count(client.get("/report/datasets-duplicate-content"), n, "duplicate set")


def test_duplicate_content_org_facet_keeps_whole_group_stats(client):
    """Filtering by publisher narrows to groups with a member in that org
    (d01/d05 are alpha, d09 is beta), but the row still shows the whole
    group's totals (3 datasets, 2 publishers), not just that org's side."""
    report = _report("datasets-duplicate-content")
    sql, params = report_facet_counts(report, {})["org"]
    options = Query(sql).all(*params)
    assert {o["slug"] for o in options} == {"alpha", "beta"}
    assert all(o["count"] == 1 for o in options)  # one group, either side

    filtered = _report_count(report, {"org": "alpha"})
    assert filtered == 1

    out = report_stmts(report, {"org": "alpha"})
    row = out["list"].all(*out["params"], 10, 0)[0]
    assert row["dataset_count"] == 3  # whole group, not just alpha's two
    assert row["org_count"] == 2

    assert client.get("/report/datasets-duplicate-content?org=alpha").status_code == 200


def test_duplicate_content_dashboard_count_is_redundant_records(client):
    """The dashboard card counts *redundant* records — every member of a
    duplicate group except the one you'd keep — so the fixture's 3-member
    group counts 2. Not the groups (1) and not all members (3), which are
    what the report page's own count and list rows use."""
    assert report_unfiltered_count("datasets-duplicate-content") == 1  # groups
    assert report_dashboard_count("datasets-duplicate-content") == 2  # 3 - 1

    cards.cache_clear()
    card = cards()["cards"]["datasets-duplicate-content"]
    assert card["count"] == 2
    # the card's unit differs from the page's, so it carries its own label
    assert card["label"] == "Duplicate datasets"
    # share of all datasets (16 in the fixture), via percent_of — the
    # "duplicate-content" kind itself is not a totals bucket
    assert card["percent"] == 2 / 16 * 100

    html = client.get(
        "/report/datasets-duplicate-content",
        {"hash": "hash-shared-d01-d05-d09"},
    ).content.decode()
    assert "Air quality data" in html  # d01
    assert "Coastal erosion observations" in html  # d05
    assert "Bus timetables" in html  # d09
    _html_case.assertInHTML("3 datasets", html)


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


def _facet_hrefs(client, url):
    html = client.get(url).content.decode()
    return re.findall(r'href="([^"]+)"\s+class="facet-link', html)


# Every page with a facet sidebar, on its default (unsorted) URL.
FACET_ROUTES = [
    "/datasets",
    "/collections",
    "/organisations",
    "/links",
    "/links/status",
    "/harvesters",
    "/reviews",
    f"/report/{REPORTS[0]['key']}",
]


@pytest.mark.parametrize("url", FACET_ROUTES)
def test_facet_links_omit_default_sort(client, url):
    """On every facet page the default sort/dir are not echoed into the facet
    links — they carry only facets. This is also the guard that a page which
    forgets to pass its sort default to preserve_params fails loudly instead
    of quietly regressing."""
    hrefs = _facet_hrefs(client, url)
    assert hrefs, f"{url} rendered no facet links"
    assert all("sort=" not in h and "dir=" not in h for h in hrefs), url


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
    html = client.get("/links/status?category=OK").content.decode()
    assert "link-errors-row--ok" in html
    assert "status--ok" in html


def _collections_count(filters):
    stmt = collections_stmts(filters, "views", "desc")
    return stmt["count"].get(*stmt["params"])["n"]


def test_collections_bogus_category_falls_back(client):
    """An unknown `?category=` is ignored — the page returns the unfiltered
    count. A valid category narrows to its pool count."""
    unfiltered = _collections_count({})
    assert_count(client.get("/collections?category=bogus"), unfiltered, "collection pages")

    # "environment" has 2 fixture collections; check the filter works.
    filtered = _collections_count({"category": "environment"})
    assert_count(client.get("/collections?category=environment"), filtered, "collection pages")

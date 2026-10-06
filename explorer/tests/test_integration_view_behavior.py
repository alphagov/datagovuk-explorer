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

from explorer.queries.collections import collections_stmts
from explorer.queries.core import Query
from explorer.queries.dashboard import cards
from explorer.queries.datasets import datasets_facet_counts, datasets_stmts
from explorer.queries.harvesters import harvest_source_rows, harvest_sources_stmts, harvested_total
from explorer.queries.link_errors import LINK_ERRORS_SORT_DEFAULT, link_errors_facet_counts, link_errors_stmts
from explorer.queries.links import LINK_SORT_DEFAULT, links_facet_counts, links_stmts
from explorer.queries.metadata import METADATA_KEYS
from explorer.queries.organisations import (
    organisations_facet_counts,
    organisations_stmts,
    publisher_reviews_facet_counts,
    publisher_reviews_stmts,
)
from explorer.queries.reports import (
    REPORTS,
    report_dashboard_count,
    report_facet_counts,
    report_stmts,
    report_unfiltered_count,
)
from explorer.queries.reviews import reviews_stmts
from explorer.queries.series import SERIES_COUNT
from explorer.queries.suggestions import SUGGESTIONS_SORT_DEFAULT, suggestions_stmts
from explorer.tests.csv_helpers import csv_rows, today_iso
from explorer.views.harvesters import HarvesterFilters, _matches
from explorer.views.suggestions import _csv_row

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


# ── /datasets CSV download (views/datasets.py) ───────────────────────────


def test_datasets_download_is_unpaginated_csv(client):
    n = _datasets_count({})
    response = client.get("/datasets/download.csv")
    assert response["Content-Disposition"] == f'attachment; filename="datasets-{today_iso()}.csv"'
    rows = csv_rows(response)
    assert len(rows) == n + 1
    assert rows[0] == [
        "Dataset",
        "Publisher",
        "Created",
        "Updated",
        "Links",
        "Views",
        "Source",
        "Dataset ID",
    ]
    assert all(row[-1] for row in rows[1:])  # dataset CKAN GUID


def test_datasets_page_offers_the_download(client):
    html = client.get("/datasets").content.decode()
    assert "/datasets/download.csv" in html
    assert "Download CSV" in html


def test_datasets_download_applies_facet_filter(client):
    publisher = datasets_facet_counts({})["publishers"][0]["value"]
    n = _datasets_count({"publisher": publisher})
    rows = csv_rows(client.get("/datasets/download.csv", {"publisher": publisher}))
    assert len(rows) == n + 1


def test_datasets_download_url_carries_the_active_filters(client):
    publisher = datasets_facet_counts({})["publishers"][0]["value"]
    html = client.get("/datasets", {"publisher": publisher, "sort": "title", "dir": "asc"}).content.decode()
    assert f"/datasets/download.csv?sort=title&amp;dir=asc&amp;publisher={publisher}" in html


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
    """The dataset detail page renders the latest ok review's title-description score
    (the fixture holds two for d01; the later one wins)."""
    html = client.get("/dataset/alpha/d01").content.decode()
    assert "Description 5/5" in html
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


def test_collections_bogus_collection_falls_back(client):
    """An unknown `?collection=` is ignored — the page returns the unfiltered
    count. A valid collection narrows to its pool count."""
    unfiltered = _collections_count({})
    assert_count(client.get("/collections?collection=bogus"), unfiltered, "collection pages")

    # "environment" has 2 fixture collections; check the filter works.
    filtered = _collections_count({"collection": "environment"})
    assert_count(client.get("/collections?collection=environment"), filtered, "collection pages")


# ── /organisations CSV download (views/organisations.py) ──────────────────


def test_organisations_download_is_unpaginated_csv(client):
    stmts = organisations_stmts({}, "views", "desc")
    n = stmts["count"].get(*stmts["params"])["n"]
    response = client.get("/organisations/download.csv")
    assert response["Content-Disposition"] == f'attachment; filename="publishers-{today_iso()}.csv"'
    rows = csv_rows(response)
    assert len(rows) == n + 1
    assert rows[0] == [
        "Publisher",
        "Datasets",
        "Links",
        "Health",
        "Views",
        "Created",
        "Last published",
        "Publisher ID",
    ]
    assert all(row[-1].startswith("uuid-") for row in rows[1:])  # CKAN org UUID from json


def test_organisations_page_offers_the_download(client):
    html = client.get("/organisations").content.decode()
    assert "/organisations/download.csv" in html
    assert "Download CSV" in html


def test_organisations_download_applies_facet_filter(client):
    bucket = organisations_facet_counts({})["datasets"][0]["bucket"]
    stmts = organisations_stmts({"datasets": bucket}, "views", "desc")
    n = stmts["count"].get(*stmts["params"])["n"]
    rows = csv_rows(client.get("/organisations/download.csv", {"datasets": bucket}))
    assert len(rows) == n + 1


def test_organisations_download_url_carries_the_active_filters(client):
    bucket = organisations_facet_counts({})["datasets"][0]["bucket"]
    html = client.get("/organisations", {"datasets": bucket, "sort": "name", "dir": "asc"}).content.decode()
    assert f"/organisations/download.csv?sort=name&amp;dir=asc&amp;datasets={bucket}" in html


def test_organisations_download_ignores_page(client):
    stmts = organisations_stmts({}, "views", "desc")
    n = stmts["count"].get(*stmts["params"])["n"]
    rows = csv_rows(client.get("/organisations/download.csv", {"page": "999"}))
    assert len(rows) == n + 1


# ── /harvesters CSV download (views/harvesters.py) ───────────────────────


def test_harvesters_download_is_unpaginated_csv(client):
    stmts = harvest_sources_stmts({}, "dataset_count", "desc")
    n = stmts["count"].get(*stmts["params"])["n"]
    response = client.get("/harvesters/download.csv")
    assert response["Content-Disposition"] == f'attachment; filename="harvesters-{today_iso()}.csv"'
    rows = csv_rows(response)
    assert len(rows) == n + 1
    assert rows[0] == [
        "Source",
        "Publisher",
        "Type",
        "Status",
        "Frequency",
        "Datasets",
        "Last run",
        "Harvest source ID",
        "Publisher ID",
    ]
    assert all(row[-2] and row[-1] for row in rows[1:])  # harvest-source + publisher UUIDs


def test_harvesters_page_offers_the_download(client):
    html = client.get("/harvesters").content.decode()
    assert "/harvesters/download.csv" in html
    assert "Download CSV" in html


def test_harvesters_download_applies_facet_filter(client):
    stmts = harvest_sources_stmts({"active": "true"}, "dataset_count", "desc")
    n = stmts["count"].get(*stmts["params"])["n"]
    rows = csv_rows(client.get("/harvesters/download.csv", {"active": "true"}))
    assert len(rows) == n + 1


def test_harvesters_download_url_carries_the_active_filters(client):
    html = client.get("/harvesters", {"active": "true", "sort": "title", "dir": "asc"}).content.decode()
    assert "/harvesters/download.csv?sort=title&amp;dir=asc&amp;active=true" in html


# ── /organisations/reviews CSV download (views/publisher_reviews.py) ──────


def test_publisher_reviews_download_is_unpaginated_csv(client):
    stmts = publisher_reviews_stmts({}, "avg_findability", "desc")
    n = stmts["count"].get(*stmts["params"])["n"]
    response = client.get("/organisations/reviews/download.csv")
    assert response["Content-Disposition"] == f'attachment; filename="publisher-reviews-{today_iso()}.csv"'
    rows = csv_rows(response)
    assert len(rows) == n + 1
    assert rows[0] == ["Publisher", "Datasets", "Description", "Links", "Publisher ID"]
    assert all(row[-1].startswith("uuid-") for row in rows[1:])  # CKAN org UUID from json


def test_publisher_reviews_page_offers_the_download(client):
    html = client.get("/organisations/reviews").content.decode()
    assert "/organisations/reviews/download.csv" in html
    assert "Download CSV" in html


def test_publisher_reviews_download_url_carries_the_active_filters(client):
    bucket = publisher_reviews_facet_counts({})["datasets"][0]["bucket"]
    html = client.get("/organisations/reviews", {"datasets": bucket, "sort": "name", "dir": "asc"}).content.decode()
    assert f"/organisations/reviews/download.csv?sort=name&amp;dir=asc&amp;datasets={bucket}" in html


# ── /series CSV download (views/series.py) ────────────────────────────────


def test_series_download_is_unpaginated_csv(client):
    n = SERIES_COUNT.get()["n"]
    response = client.get("/series/download.csv")
    assert response["Content-Disposition"] == f'attachment; filename="series-{today_iso()}.csv"'
    rows = csv_rows(response)
    assert len(rows) == n + 1
    assert rows[0] == ["Title", "Type", "Datasets", "Orgs", "Series ID"]
    assert all(row[-1] for row in rows[1:])  # series id (the /series/{id} link key)


def test_series_page_offers_the_download(client):
    html = client.get("/series").content.decode()
    assert "/series/download.csv" in html
    assert "Download CSV" in html


def test_series_download_url_carries_the_sort(client):
    html = client.get("/series", {"sort": "root_title", "dir": "asc"}).content.decode()
    assert "/series/download.csv?sort=root_title&amp;dir=asc" in html


# ── /reviews CSV download (views/reviews.py) ──────────────────────────────


def test_reviews_download_is_unpaginated_csv(client):
    stmts = reviews_stmts({}, "findability", "asc")
    n = stmts["count"].get(*stmts["params"])["n"]
    response = client.get("/reviews/download.csv")
    assert response["Content-Disposition"] == f'attachment; filename="reviews-{today_iso()}.csv"'
    rows = csv_rows(response)
    assert len(rows) == n + 1
    assert rows[0] == ["Dataset", "Publisher", "Description", "Links", "Dataset ID"]
    assert all(row[-1] for row in rows[1:])  # dataset CKAN GUID


def test_reviews_page_offers_the_download(client):
    html = client.get("/reviews").content.decode()
    assert "/reviews/download.csv" in html
    assert "Download CSV" in html


def test_reviews_download_applies_score_filter(client):
    stmts = reviews_stmts({"findability": "5"}, "findability", "asc")
    n = stmts["count"].get(*stmts["params"])["n"]
    rows = csv_rows(client.get("/reviews/download.csv", {"findability": "5"}))
    assert len(rows) == n + 1


def test_reviews_download_url_carries_the_active_filters(client):
    html = client.get("/reviews", {"findability": "5", "sort": "title", "dir": "asc"}).content.decode()
    assert "/reviews/download.csv?sort=title&amp;dir=asc&amp;findability=5" in html


# ── /suggestions CSV download (views/suggestions.py) ──────────────────────


def test_suggestions_download_is_unpaginated_csv(client):
    stmts = suggestions_stmts({}, *SUGGESTIONS_SORT_DEFAULT)
    n = stmts["count"].get(*stmts["params"])["n"]
    response = client.get("/suggestions/download.csv")
    assert response["Content-Disposition"] == f'attachment; filename="suggestions-{today_iso()}.csv"'
    rows = csv_rows(response)
    assert len(rows) == n + 1
    assert rows[0] == [
        "Current title",
        "Suggested title",
        "Publisher",
        "Current theme",
        "Suggested theme",
        "Current tags",
        "Suggested tags",
        "Confidence",
        "Dataset ID",
    ]
    assert all(row[-1] for row in rows[1:])  # dataset CKAN GUID


def test_suggestions_csv_row_normalises_tags_to_semicolons():
    row = _csv_row(
        {
            "title": "T",
            "suggested_title": "S",
            "org_display_name": "O",
            "current_theme": "x",
            "theme": "y",
            "theme_confidence": "high",
            "current_tags": "alpha  beta gamma",
            "tags": '["one", "two"]',
            "ckan_id": "g",
        },
    )
    assert row["current_tags"] == "alpha; beta; gamma"
    assert row["tags"] == "one; two"


def test_suggestions_page_offers_the_download(client):
    html = client.get("/suggestions").content.decode()
    assert "/suggestions/download.csv" in html
    assert "Download CSV" in html


def test_suggestions_download_applies_theme_filter(client):
    stmts = suggestions_stmts({"theme": "none"}, *SUGGESTIONS_SORT_DEFAULT)
    n = stmts["count"].get(*stmts["params"])["n"]
    rows = csv_rows(client.get("/suggestions/download.csv", {"theme": "none"}))
    assert len(rows) == n + 1


def test_suggestions_download_url_carries_the_active_filters(client):
    html = client.get("/suggestions", {"theme": "none", "sort": "title", "dir": "asc"}).content.decode()
    assert "/suggestions/download.csv?sort=title&amp;dir=asc&amp;theme=none" in html


# ── /links CSV download (views/links.py) ─────────────────────────────────


def test_links_download_is_unpaginated_csv(client):
    stmts = links_stmts({}, *LINK_SORT_DEFAULT)
    n = stmts["count"].get(*stmts["params"])["n"]
    response = client.get("/links/download.csv")
    assert response["Content-Disposition"] == f'attachment; filename="links-{today_iso()}.csv"'
    rows = csv_rows(response)
    assert len(rows) == n + 1
    assert rows[0] == ["Name", "URL", "Format", "Dataset", "Publisher", "Dataset ID", "Resource ID"]
    assert all(row[-1] for row in rows[1:])  # link resource GUID
    assert all(row[-2] for row in rows[1:])  # dataset CKAN GUID


def test_links_page_offers_the_download(client):
    html = client.get("/links").content.decode()
    assert "/links/download.csv" in html
    assert "Download CSV" in html


def test_links_download_applies_facet_filter(client):
    fmt = links_facet_counts({})["formats"][0]["fmt"]
    filters = {"domain": None, "format": fmt, "created_year": None, "publisher": None}
    stmts = links_stmts(filters, *LINK_SORT_DEFAULT)
    n = stmts["count"].get(*stmts["params"])["n"]
    rows = csv_rows(client.get("/links/download.csv", {"format": fmt}))
    assert len(rows) == n + 1


def test_links_download_url_carries_the_active_filters(client):
    pub = links_facet_counts({})["publishers"][0]["value"]
    html = client.get("/links", {"publisher": pub, "sort": "name", "dir": "asc"}).content.decode()
    assert f"/links/download.csv?sort=name&amp;dir=asc&amp;publisher={pub}" in html


# ── /links/status CSV download (views/links_errors.py) ────────────────────


def test_link_errors_download_is_unpaginated_csv(client):
    stmts = link_errors_stmts({}, *LINK_ERRORS_SORT_DEFAULT)
    n = stmts["count"].get(*stmts["params"])["n"]
    response = client.get("/links/status/download.csv")
    assert response["Content-Disposition"] == f'attachment; filename="link-status-{today_iso()}.csv"'
    rows = csv_rows(response)
    assert len(rows) == n + 1
    assert rows[0] == [
        "URL",
        "Status",
        "HTTP Status",
        "Dataset",
        "Publisher",
        "Harvested",
        "Dataset ID",
        "Resource ID",
    ]
    assert all(row[-1] for row in rows[1:])  # link resource GUID


def test_link_errors_page_offers_the_download(client):
    html = client.get("/links/status").content.decode()
    assert "/links/status/download.csv" in html
    assert "Download CSV" in html


def test_link_errors_download_applies_category_filter(client):
    cat = link_errors_facet_counts({})["categories"][0]["value"]
    filters = {"category": cat, "status": None, "domain": None, "harvested": None, "publisher": None}
    stmts = link_errors_stmts(filters, *LINK_ERRORS_SORT_DEFAULT)
    n = stmts["count"].get(*stmts["params"])["n"]
    rows = csv_rows(client.get("/links/status/download.csv", {"category": cat}))
    assert len(rows) == n + 1


def test_link_errors_download_filename_reflects_the_filter(client):
    response = client.get("/links/status/download.csv", {"category": "NOT_FOUND"})
    assert response["Content-Disposition"] == (
        f'attachment; filename="link-status-category-not-found-{today_iso()}.csv"'
    )


def test_link_errors_download_url_carries_the_active_filters(client):
    cat = link_errors_facet_counts({})["categories"][0]["value"]
    html = client.get("/links/status", {"category": cat, "sort": "url", "dir": "desc"}).content.decode()
    assert f"/links/status/download.csv?sort=url&amp;dir=desc&amp;category={cat}" in html


# ── /metadata CSV download (views/metadata.py) ────────────────────────────


def test_metadata_download_is_unpaginated_csv(client):
    n = len(METADATA_KEYS.all())
    response = client.get("/metadata/download.csv")
    assert response["Content-Disposition"] == f'attachment; filename="metadata-{today_iso()}.csv"'
    rows = csv_rows(response)
    assert len(rows) == n + 1
    assert rows[0] == ["Field", "Section", "Used by", "Unique values", "% of catalogue"]
    assert all(row[0] for row in rows[1:])  # field label
    assert {row[1] for row in rows[1:]} <= {"top", "extras"}
    used = [int(row[2]) for row in rows[1:]]
    assert used == sorted(used, reverse=True)  # same usage ranking as the table


def test_metadata_page_offers_the_download_without_a_pager(client):
    """The overview has no pager, so the menu must render on its own."""
    html = client.get("/metadata").content.decode()
    assert "/metadata/download.csv" in html
    assert "Download CSV" in html
    assert 'class="pagination"' not in html

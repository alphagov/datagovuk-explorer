"""Integration tests for the data-quality reports against the seeded fixture.

Every report's count/list compiles and agrees, ordering is deterministic, the
facet counts wire up to the right (sql, params), and every report offers its
filtered, unpaginated rows as a CSV download.
"""

import csv
import io

import pytest

from explorer.queries.core import Query
from explorer.queries.reports import REPORTS, report_facet_counts, report_stmts

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

_DOWNLOAD = "/report/{key}/download.csv"


def _report(key):
    return next(r for r in REPORTS if r["key"] == key)


def _count(report, filters=None):
    out = report_stmts(report, filters)
    return out["count"].get(*out["params"])["n"]


def _csv_rows(response):
    """A download response's rows as lists, header included."""
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    return list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))


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


# ── CSV download (views/reports.py's report_download) ─────────────────────


@pytest.mark.parametrize("report", REPORTS, ids=[r["key"] for r in REPORTS])
def test_every_report_download_is_unpaginated_csv(client, report):
    """The download is the report's full filtered row set (no pager) plus a
    header, with an attachment filename named after the report."""
    response = client.get(_DOWNLOAD.format(key=report["key"]))
    assert response["Content-Disposition"] == f'attachment; filename="{report["key"]}.csv"'
    rows = _csv_rows(response)
    assert len(rows) == _count(report) + 1, f"{report['key']}: wrong row count"


@pytest.mark.parametrize("report", REPORTS, ids=[r["key"] for r in REPORTS])
def test_every_report_page_offers_the_download(client, report):
    html = client.get(f"/report/{report['key']}").content.decode()
    assert f"/report/{report['key']}/download.csv" in html
    assert "Download CSV" in html


def test_report_download_applies_facet_filter(client):
    report = _report("datasets-no-description")
    sql, params = report_facet_counts(report, {})["org"]
    top = Query(sql).all(*params)[0]
    rows = _csv_rows(client.get(_DOWNLOAD.format(key=report["key"]), {"org": top["slug"]}))
    assert len(rows) == _count(report, {"org": top["slug"]}) + 1


def test_report_download_url_carries_the_active_filters(client):
    report = _report("datasets-no-description")
    sql, params = report_facet_counts(report, {})["org"]
    top = Query(sql).all(*params)[0]
    html = client.get(f"/report/{report['key']}", {"org": top["slug"], "sort": "title", "dir": "asc"}).content.decode()
    assert f"/report/{report['key']}/download.csv?sort=title&amp;dir=asc&amp;org={top['slug']}" in html


def test_report_download_ignores_page(client):
    """?page= must not shrink the export — the pager is a page concern."""
    report = _report("datasets-no-description")
    rows = _csv_rows(client.get(_DOWNLOAD.format(key=report["key"]), {"page": "999"}))
    assert len(rows) == _count(report) + 1


def test_report_download_order_matches_the_sorted_query(client):
    report = _report("datasets-no-description")
    out = report_stmts(report, {}, sort="title", dir_="asc")
    expected = [r["title"] or r["name"] for r in out["list"].all(*out["params"], 1_000_000, 0)]
    rows = _csv_rows(client.get(_DOWNLOAD.format(key=report["key"]), {"sort": "title", "dir": "asc"}))
    assert [row[0] for row in rows[1:]] == expected


def test_duplicate_content_detail_download(client):
    """Detail mode exports its members as the datasets shape (the three
    fixture datasets sharing the content hash)."""
    rows = _csv_rows(
        client.get(_DOWNLOAD.format(key="datasets-duplicate-content"), {"hash": "hash-shared-d01-d05-d09"}),
    )
    assert len(rows) == 4  # header + the three members
    assert rows[0] == ["Dataset", "Publisher", "Created", "Modified", "Views", "Dataset ID"]
    assert {row[-1] for row in rows[1:]} == {"d01", "d05", "d09"}


def test_duplicate_url_detail_download(client):
    report = _report("links-duplicate-urls")
    listing = report_stmts(report)
    url = listing["list"].all(*listing["params"], 1, 0)[0]["url"]
    rows = _csv_rows(client.get(_DOWNLOAD.format(key=report["key"]), {"url": url}))
    assert len(rows) == Query(report["detail_count_sql"]).get(url)["n"] + 1
    # Detail is the links shape; the shared URL is dropped but both GUIDs ride along.
    assert rows[0] == ["Name", "Format", "Dataset", "Publisher", "Dataset ID", "Resource ID"]
    assert all(row[-2] and row[-1] for row in rows[1:])

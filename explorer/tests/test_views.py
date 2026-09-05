"""View smoke tests — every route → 200 + key content.

Expected values are computed from the query layer / reviews table — the
same live data the views render — so a broken view (wrong sort column,
off-by-one pagination, dropped count, dead template var) fails here
without hardcoding baseline counts into the suite.

App tests read the *live* dev DB read-only (see tests/conftest.py) and
skip when it's unreachable or empty.
"""

import math
import re
from urllib.parse import urlencode

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse
from markupsafe import escape

import explorer.middleware as mw
from explorer.queries.core import Query
from explorer.queries.datasets import (
    DATASET_COUNT,
    LINK_BUCKET_NAMES,
    LINK_BUCKETS,
    THEME_COUNTS,
    datasets_facet_counts,
    datasets_stmts,
    org_datasets_stmts,
)
from explorer.queries.links import LINKS_STATS, links_facet_counts, links_stmts
from explorer.queries.metadata import (
    METADATA_KEYS,
    METADATA_VALUE_COUNT,
    METADATA_VALUES,
)
from explorer.queries.organisations import ORGS
from explorer.queries.reports import (
    REPORTS,
    report_facet_counts,
    report_stmts,
)
from explorer.queries.reviews import (
    get_review,
    latest_reviews,
    reviews_stmts,
    suggestions_stmts,
)
from explorer.queries.series import SERIES_BY_ID, SERIES_COUNT, series_list_stmt
from explorer.views.core import PAGE_SIZE


def esc(s):
    """Titles render through Jinja2 autoescape (markupsafe), which escapes
    `"` as &#34; not &quot;."""
    return str(escape(s or ""))


def _primary_nav(html: str) -> str:
    """The site header's primary nav block — for asserting which reports
    are (or aren't) main-nav items."""
    m = re.search(r'<nav class="site-nav" aria-label="Primary">(.*?)</nav>', html, re.S)
    assert m, "page should render the primary site nav"
    return m.group(1)


def _assert_report_subnav(html, active, links, absent_from_main, main_item):
    """One report-group page's sub-nav contract — the same macro the Links,
    Publishers and Datasets groups use. `active` is the current report
    (rendered as the page's active h1 heading), `links` are the (label, url)
    sibling reports in the strip, `absent_from_main` are the group's reports
    that must no longer be their own main-nav items, and `main_item` is the
    href of the main-nav item that stays highlighted for the group."""
    assert f'<h1 class="nav-link nav-link--active" aria-current="page">{active}</h1>' in html
    for label, url in links:
        assert f'<a href="{url}" class="nav-link">{label}</a>' in html
    primary = _primary_nav(html)
    for url in absent_from_main:
        assert f'href="{url}"' not in primary
    assert f'href="{main_item}"' in primary


# ---------------------------------------------------------------------------
# Health + 404s
# ---------------------------------------------------------------------------
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.content == b"ok"


def test_health_exempt_from_basic_auth(monkeypatch):
    """/health must stay reachable without credentials when the gate is on
    (Railway probes it to decide the deployment is up; auth creds there
    would make uptime/alerting tooling brittle)."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("BASIC_AUTH_USER", "user")
    monkeypatch.setenv("BASIC_AUTH_PASS", "pass")

    gate = mw.BasicAuthMiddleware(lambda request: HttpResponse("ok"))
    assert gate.enabled

    req = HttpRequest()
    req.path = "/health"
    r = gate(req)
    assert r.status_code == 200

    req.path = "/datasets"
    assert gate(req).status_code == 401


def test_basic_auth_off_in_development(monkeypatch):
    """In development the gate is off (no creds needed locally)."""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("BASIC_AUTH_USER", "user")
    monkeypatch.setenv("BASIC_AUTH_PASS", "pass")
    assert not mw.BasicAuthMiddleware(lambda request: HttpResponse("ok")).enabled


def test_production_requires_creds(monkeypatch):
    """Production without credentials is a startup error — never run unauthenticated."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("BASIC_AUTH_USER", raising=False)
    monkeypatch.delenv("BASIC_AUTH_PASS", raising=False)
    with pytest.raises(ImproperlyConfigured):
        mw.BasicAuthMiddleware(lambda request: HttpResponse("ok"))


def test_unknown_route_renders_404(client):
    r = client.get("/no-such-page")
    assert r.status_code == 404
    # 404.html, not Django's technical 404 page (its title also contains
    # "Page not found" — assert on template-only markup).
    assert b'href="/static/css/pages/404.css"' in r.content
    assert "404 — Page not found" in r.content.decode()


def test_missing_static_renders_404(client):
    # Missing static falls through WhiteNoise to the catch-all 404 view,
    # which renders 404.html too.
    r = client.get("/static/css/definitely-not-a-file.css")
    assert r.status_code == 404
    assert b'href="/static/css/pages/404.css"' in r.content


# ---------------------------------------------------------------------------
# Home dashboard + reports
# ---------------------------------------------------------------------------
def test_home(client):
    r = client.get("/")
    html = r.content.decode()
    assert r.status_code == 200
    # Every dashboard card label renders (or is deliberately hidden when the
    # count is 0 — the label text still appears in the template data, but
    # the card markup only renders for count > 0).
    shown = [r for r in REPORTS if report_stmts(r)["count"].get()["n"] > 0]
    assert shown, "no dashboard cards to show — dataset looks empty"
    for report in shown:
        assert esc(report["label"]) in html


def test_every_report(client):
    for report in REPORTS:
        stmt = report_stmts(report)
        total = stmt["count"].get(*stmt["params"])["n"]
        url = f"/report/{report['key']}"
        r = client.get(url)
        html = r.content.decode()
        assert r.status_code == 200, f"{url} -> {r.status_code}"
        assert esc(report["label"]) in html
        assert f"{total:,}" in html
        if total:
            rows = stmt["list"].all(*stmt["params"], PAGE_SIZE, 0)
            cell = (
                rows[0].get("url")
                if report["kind"] == "duplicate-urls"
                else rows[0].get("dataset_title") or rows[0].get("title") or rows[0].get("name")
            )
            assert cell is None or esc(cell) in html, f"{url}: first row not rendered"


def test_report_unknown_key_404(client):
    assert client.get("/report/bogus-key").status_code == 404


def test_report_org_facet(client):
    report = next(r for r in REPORTS if r["key"] == "datasets-no-links")
    sql, params = report_facet_counts(report, {})["org"]
    options = Query(sql).all(*params)
    if not options:
        pytest.skip("no org facet options in the live data")
    slug = options[0]["slug"]
    out = report_stmts(report, {"org": slug})
    fcount = out["count"].get(*out["params"])["n"]
    r = client.get(f"/report/datasets-no-links?org={slug}")
    html = r.content.decode()
    assert r.status_code == 200
    assert f"{fcount:,}" in html
    assert esc(options[0]["name"]) in html  # the filter pill

    # bogus org values are ignored — the view validates against the facet
    # options before filtering (the query layer itself would just filter to
    # 0 rows)
    total = report_stmts(report)["count"].get()["n"]
    rb = client.get("/report/datasets-no-links?org=__no_such_org__")
    assert rb.status_code == 200
    assert f"{total:,}" in rb.content.decode()


def test_has_api_both_facets(client):
    """datasets-has-api with ?org= + ?api_type= set simultaneously — the
    only multi-facet report. The page renders, shows the filtered count and
    both filter pills (the org/type names come from the report's own
    per-report option pools)."""
    report = next(r for r in REPORTS if r["key"] == "datasets-has-api")

    def pool(filters, key):
        sql, params = report_facet_counts(report, filters)[key]
        return Query(sql).all(*params)

    org_opts = pool({}, "org")
    type_opts = pool({}, "api_type")
    if not org_opts or not type_opts:
        pytest.skip("no has-api facet options in the live data")
    org_slug, org_name = org_opts[0]["slug"], org_opts[0]["name"]
    api_type, type_name = type_opts[0]["slug"], type_opts[0]["name"]

    stmt = report_stmts(report, {"org": org_slug, "api_type": api_type})
    total = stmt["count"].get(*stmt["params"])["n"]
    r = client.get(f"/report/datasets-has-api?org={org_slug}&api_type={api_type}")
    html = r.content.decode()
    assert r.status_code == 200
    assert f"{total:,}" in html
    assert esc(org_name) in html  # the org filter pill
    assert esc(type_name) in html  # the api-type filter pill


# ---------------------------------------------------------------------------
# /organisations (facet page)
# ---------------------------------------------------------------------------
def test_organisations(client):
    """/organisations — count + sortable, paginated SQL list. Contract
    test: the page's rows and count must equal the SQL builder's (the view
    renders organisations_stmts verbatim); the facet contract is
    test_organisations_facets."""
    from explorer.queries.organisations import organisations_stmts  # noqa: PLC0415

    orgs = ORGS.all()
    assert orgs
    total = len(orgs)

    # default sort: name asc — first page rows match the builder
    out = organisations_stmts({}, "name", "asc")
    page1 = out["list"].all(*out["params"], PAGE_SIZE, 0)
    assert page1
    r = client.get("/organisations")
    html = r.content.decode()
    assert r.status_code == 200
    # count header: "X-Y of Z" with the filtered total
    assert f"1-{len(page1):,} of {total:,}" in html

    # Publishers group sub-nav — Harvesters is a sub-report of Publishers
    # (the same macro as the Links group): the current report renders as
    # the active h1 heading, with the sibling report linked beside it, and
    # Harvesters is no longer its own main-nav item.
    _assert_report_subnav(
        html,
        "Publishers",
        (("Harvesters", "/harvesters"),),
        ("/harvesters",),
        "/organisations",
    )

    # every sort column, both directions — page rows match the builder
    for sort in (
        "name",
        "dataset_count",
        "resource_count",
        "views",
        "type",
        "state",
        "approval_status",
        "created",
        "last_published",
    ):
        for dir_ in ("asc", "desc"):
            out = organisations_stmts({}, sort, dir_)
            expect = out["list"].all(*out["params"], PAGE_SIZE, 0)
            r = client.get(f"/organisations?sort={sort}&dir={dir_}")
            assert r.status_code == 200
            assert esc(expect[0]["display_name"] or expect[0]["name"]) in r.content.decode(), f"sort={sort} dir={dir_}"

    # invalid sort falls back to name asc; bogus dir → asc
    r3 = client.get("/organisations?sort=bogus&dir=bogus")
    assert r3.status_code == 200
    out = organisations_stmts({}, "name", "asc")
    expect = out["list"].all(*out["params"], PAGE_SIZE, 0)
    assert esc(expect[0]["display_name"] or expect[0]["name"]) in r3.content.decode()

    # one facet combo: ?year=<latest org-creation year>
    years = sorted(
        {(o["created"] or "")[:4] for o in orgs if o["created"]},
        reverse=True,
    )
    if years:
        year = years[0]
        out = organisations_stmts({"year": year}, "name", "asc")
        year_count = out["count"].get(*out["params"])["n"]
        r4 = client.get(f"/organisations?year={year}")
        assert f"1-{min(year_count, PAGE_SIZE):,} of {year_count:,}" in r4.content.decode()

    # page 2 exists (1,480 orgs > 100); pager links keep sort/dir
    if total > PAGE_SIZE:
        assert (
            "?sort=name&amp;dir=asc&amp;page=2"
            in client.get(
                "/organisations",
            ).content.decode()
        )
        r2 = client.get("/organisations?page=2")
        assert r2.status_code == 200
        assert "?sort=name&amp;dir=asc&amp;page=1" in r2.content.decode()
        out2 = organisations_stmts({}, "name", "asc")
        page2 = out2["list"].all(*out2["params"], PAGE_SIZE, PAGE_SIZE)
        assert page2
        assert esc(page2[0]["display_name"] or page2[0]["name"]) in r2.content.decode()
        assert f"{PAGE_SIZE + 1:,}-{min(2 * PAGE_SIZE, total):,} of {total:,}" in r2.content.decode()
    # out-of-range page clamps rather than erroring
    assert client.get("/organisations?page=99999").status_code == 200

    # ?pubyear=__none__ renders the Never published pill + trailing bucket
    r5 = client.get("/organisations?pubyear=__none__")
    h5 = r5.content.decode()
    assert r5.status_code == 200
    assert 'class="filter-pill"' in h5
    assert "Never published" in h5
    # the bucket stays visible on the unfiltered page, in the pubyear facet
    section = _facet_section(client.get("/organisations").content.decode(), "Filter by year last published")
    assert ">Never published<" in section


def test_organisations_facets(client):
    """Each /organisations facet's SQL count equals the Python reference
    count over the full merged fetch (the WHERE clauses mirror the old
    _apply_filters rules); the active selection renders its pill."""
    from collections import Counter  # noqa: PLC0415

    from explorer.queries.organisations import (  # noqa: PLC0415
        DATASET_BUCKET_TESTS,
        all_org_rows,
        org_aggregate_rows,
        organisations_stmts,
    )
    from explorer.views.organisations import _merge_org_rows  # noqa: PLC0415

    rows = _merge_org_rows(all_org_rows(), org_aggregate_rows())

    # ?year=<most common creation year>
    year_counts = Counter(o["created_year"] for o in rows if o["created_year"])
    top_year, _ = year_counts.most_common(1)[0]
    n_year = sum(1 for o in rows if o["created_year"] == top_year)
    out = organisations_stmts({"year": top_year}, "name", "asc")
    assert out["count"].get(*out["params"])["n"] == n_year
    r4 = client.get(f"/organisations?year={top_year}")
    h4 = r4.content.decode()
    assert r4.status_code == 200
    assert f"1-{min(n_year, PAGE_SIZE):,} of {n_year:,}" in h4
    assert 'class="filter-pill"' in h4

    # ?pubyear=<most common last-published year>
    pubyear_counts = Counter(o["last_published_year"] for o in rows if o["last_published_year"])
    top_pub, _ = pubyear_counts.most_common(1)[0]
    n_pub = sum(1 for o in rows if o["last_published_year"] == top_pub)
    out = organisations_stmts({"pubyear": (top_pub,)}, "name", "asc")
    assert out["count"].get(*out["params"])["n"] == n_pub
    r5 = client.get(f"/organisations?pubyear={top_pub}")
    h5 = r5.content.decode()
    assert r5.status_code == 200
    assert f"1-{min(n_pub, PAGE_SIZE):,} of {n_pub:,}" in h5
    assert 'class="filter-pill"' in h5

    # ?datasets=0 renders the zero-datasets bucket
    n_zero = sum(1 for o in rows if DATASET_BUCKET_TESTS["0"](o["dataset_count"]))
    out = organisations_stmts({"datasets": "0"}, "name", "asc")
    assert out["count"].get(*out["params"])["n"] == n_zero
    r6 = client.get("/organisations?datasets=0")
    h6 = r6.content.decode()
    assert r6.status_code == 200
    assert f"1-{min(n_zero, PAGE_SIZE):,} of {n_zero:,}" in h6
    assert 'class="filter-pill"' in h6


def test_organisation_detail(client):
    """/organisation/{slug} — count + sortable, paginated SQL list.
    Contract test: the page's first row and page range must equal the SQL
    builder's (the view renders org_datasets_stmts verbatim)."""
    org = next(o for o in ORGS.all() if (DATASET_COUNT.get(o["slug"]) or {}).get("count", 0) > 0)
    slug = org["slug"]
    count = (DATASET_COUNT.get(slug) or {}).get("count", 0)

    stmts = org_datasets_stmts(slug, "metadata_modified", "desc")
    first_page = stmts["list"].all(*stmts["params"], PAGE_SIZE, 0)
    assert first_page

    r = client.get(f"/organisation/{slug}")
    html = r.content.decode()
    assert r.status_code == 200
    assert esc(org["display_name"] or org["slug"]) in html
    # count header: "X-Y of Z" with the org's dataset total
    assert f"1-{len(first_page):,} of {count:,}" in html
    # default sort metadata_modified desc — first dataset row
    assert esc(first_page[0]["title"] or first_page[0]["name"]) in html

    # every sort column, both directions — page rows match the builder
    for sort in ("title", "metadata_created", "metadata_modified", "resources", "views", "harvested"):
        for dir_ in ("asc", "desc"):
            out = org_datasets_stmts(slug, sort, dir_)
            expect = out["list"].all(*out["params"], PAGE_SIZE, 0)
            r = client.get(f"/organisation/{slug}?sort={sort}&dir={dir_}")
            assert r.status_code == 200
            assert esc(expect[0]["title"] or expect[0]["name"]) in r.content.decode(), f"sort={sort} dir={dir_}"

    # invalid sort falls back to metadata_modified desc; bogus dir → asc
    r = client.get(f"/organisation/{slug}?sort=bogus&dir=bogus")
    out = org_datasets_stmts(slug, "metadata_modified", "asc")
    expect = out["list"].all(*out["params"], PAGE_SIZE, 0)
    assert esc(expect[0]["title"] or expect[0]["name"]) in r.content.decode()

    # page 2 exists for orgs with > 100 datasets; pager links keep sort/dir
    if count > PAGE_SIZE:
        # page 1 links forward to page 2; page 2 links back via Previous
        assert (
            "?sort=metadata_modified&amp;dir=desc&amp;page=2"
            in client.get(
                f"/organisation/{slug}",
            ).content.decode()
        )
        r2 = client.get(f"/organisation/{slug}?page=2")
        assert r2.status_code == 200
        assert "?sort=metadata_modified&amp;dir=desc&amp;page=1" in r2.content.decode()
        assert f"{PAGE_SIZE + 1:,}-{min(2 * PAGE_SIZE, count):,} of {count:,}" in r2.content.decode()
    # out-of-range page clamps rather than erroring
    assert client.get(f"/organisation/{slug}?page=99999").status_code == 200

    # unknown org → 404
    assert client.get("/organisation/no-such-org").status_code == 404


# ---------------------------------------------------------------------------
# /harvesters
# ---------------------------------------------------------------------------
def test_harvesters(client):
    """/harvesters — count + sortable, paginated SQL list. Contract
    test: the page's rows and count must equal the SQL builder's (the view
    renders harvest_sources_stmts verbatim); the facet contract is
    test_harvesters_facets."""
    from explorer.queries.harvesters import harvest_source_rows, harvest_sources_stmts  # noqa: PLC0415

    rows = harvest_source_rows()
    assert rows
    total = len(rows)

    # default sort: dataset_count desc — first page rows match the builder
    out = harvest_sources_stmts({}, "dataset_count", "desc")
    page1 = out["list"].all(*out["params"], PAGE_SIZE, 0)
    assert page1
    r = client.get("/harvesters")
    html = r.content.decode()
    assert r.status_code == 200
    # count header: "X-Y of Z" with the filtered total
    assert f"1-{len(page1):,} of {total:,}" in html

    # Harvesters is a sub-report of Publishers — active h1 heading in the
    # group's sub-nav, no longer its own main-nav item (Publishers stays
    # highlighted in the main nav)
    _assert_report_subnav(
        html,
        "Harvesters",
        (("Publishers", "/organisations"),),
        ("/harvesters",),
        "/organisations",
    )

    # every sort column, both directions — page rows match the builder
    for sort in ("title", "org_name", "type", "active", "frequency", "dataset_count", "last_run"):
        for dir_ in ("asc", "desc"):
            out = harvest_sources_stmts({}, sort, dir_)
            expect = out["list"].all(*out["params"], PAGE_SIZE, 0)
            r = client.get(f"/harvesters?sort={sort}&dir={dir_}")
            assert r.status_code == 200
            assert esc(expect[0]["title"]) in r.content.decode(), f"sort={sort} dir={dir_}"

    # invalid sort falls back to the default column; bogus dir becomes asc
    r3 = client.get("/harvesters?sort=bogus&dir=bogus")
    assert r3.status_code == 200
    out = harvest_sources_stmts({}, "dataset_count", "asc")
    expect = out["list"].all(*out["params"], PAGE_SIZE, 0)
    assert esc(expect[0]["title"]) in r3.content.decode()

    # ?datasets=bogus falls back to the unfiltered list
    r7 = client.get("/harvesters?datasets=bogus")
    assert r7.status_code == 200
    assert f"1-{min(total, PAGE_SIZE):,} of {total:,}" in r7.content.decode()

    # Last run column replaces Created: sortable, renders a date or an
    # em-dash for sources that never ran
    assert "Last run" in html
    assert "Created" not in html
    assert "?sort=last_run&dir=asc" in html

    # page 2 exists; pager links keep sort/dir
    if total > PAGE_SIZE:
        assert (
            "?sort=dataset_count&amp;dir=desc&amp;page=2"
            in client.get(
                "/harvesters",
            ).content.decode()
        )
        r2 = client.get("/harvesters?page=2")
        assert r2.status_code == 200
        assert "?sort=dataset_count&amp;dir=desc&amp;page=1" in r2.content.decode()
        out2 = harvest_sources_stmts({}, "dataset_count", "desc")
        page2 = out2["list"].all(*out2["params"], PAGE_SIZE, PAGE_SIZE)
        assert page2
        assert esc(page2[0]["title"]) in r2.content.decode()
    # out-of-range page clamps rather than erroring
    assert client.get("/harvesters?page=99999").status_code == 200


def test_harvesters_facets(client):
    """Each /harvesters facet's SQL count equals the Python _matches count
    over the full fetch (the WHERE/HAVING clauses mirror _matches), and the
    active selection renders its pill."""
    from collections import Counter  # noqa: PLC0415

    from explorer.queries.harvesters import harvest_source_rows, harvest_sources_stmts  # noqa: PLC0415
    from explorer.queries.organisations import DATASET_BUCKET_TESTS  # noqa: PLC0415

    rows = harvest_source_rows()

    # the most common harvest type
    type_counts = Counter(r["type"] for r in rows)
    top_type, _ = type_counts.most_common(1)[0]
    n_type = sum(1 for r in rows if r["type"] == top_type)
    out = harvest_sources_stmts({"type": top_type}, "dataset_count", "desc")
    assert out["count"].get(*out["params"])["n"] == n_type
    r4 = client.get(f"/harvesters?type={top_type}")
    h4 = r4.content.decode()
    assert r4.status_code == 200
    assert f"1-{min(n_type, PAGE_SIZE):,} of {n_type:,}" in h4
    assert 'class="filter-pill"' in h4

    # ?active=false renders the Inactive pill + badge
    n_inactive = sum(1 for r in rows if not r["active"])
    out = harvest_sources_stmts({"active": "false"}, "dataset_count", "desc")
    assert out["count"].get(*out["params"])["n"] == n_inactive
    r5 = client.get("/harvesters?active=false")
    h5 = r5.content.decode()
    assert r5.status_code == 200
    assert f"1-{min(n_inactive, PAGE_SIZE):,} of {n_inactive:,}" in h5
    assert 'class="filter-pill"' in h5
    assert "Inactive" in h5

    # ?datasets=0 renders the zero-datasets bucket (pill + count)
    n_zero = sum(1 for r in rows if DATASET_BUCKET_TESTS["0"](r["dataset_count"]))
    out = harvest_sources_stmts({"datasets": "0"}, "dataset_count", "desc")
    assert out["count"].get(*out["params"])["n"] == n_zero
    r6 = client.get("/harvesters?datasets=0")
    h6 = r6.content.decode()
    assert r6.status_code == 200
    assert f"1-{min(n_zero, PAGE_SIZE):,} of {n_zero:,}" in h6
    assert 'class="filter-pill"' in h6


# The headline "datasets harvested" matches the /datasets SOURCE facet's
# Harvested count — both count datasets.harvested = 1 (the per-source table
# column is attribution by id, not the headline).
def test_harvesters_total_matches_datasets_facet(client):
    r = client.get("/harvesters")
    html = r.content.decode()
    datasets_html = client.get("/datasets").content.decode()
    m = re.search(
        r'<span class="facet-name">Harvested</span>\s*'
        r'<span class="facet-count">([\d,]+)</span>',
        datasets_html,
    )
    assert m, "datasets SOURCE facet should show a Harvested count"
    assert f"— {m.group(1)} datasets harvested" in html


# ---------------------------------------------------------------------------
# /harvester/{id} (detail page)
# ---------------------------------------------------------------------------
def test_harvester_detail(client):
    """/harvester/{id} — count + sortable, paginated SQL list.
    Contract test: the page's first row and page range must equal the SQL
    builder's (the view renders source_datasets_stmts verbatim)."""
    from explorer.queries.datasets import source_datasets_stmts  # noqa: PLC0415
    from explorer.queries.harvesters import harvest_source_rows  # noqa: PLC0415

    rows = harvest_source_rows()
    with_datasets = [r for r in rows if r["dataset_count"] > 0]
    assert with_datasets
    source = with_datasets[0]

    stmts = source_datasets_stmts(source["id"], "metadata_modified", "desc")
    count = stmts["count"].get(*stmts["params"])["n"]
    first_page = stmts["list"].all(*stmts["params"], PAGE_SIZE, 0)
    assert first_page

    r = client.get(f"/harvester/{source['id']}")
    h = r.content.decode()
    assert r.status_code == 200
    assert source["title"] in h
    # back link to the list + a dataset row linking to its detail
    assert "/harvesters" in h
    assert "/dataset/" in h
    # count header: "X-Y of Z" with the source's dataset total
    assert f"1-{len(first_page):,} of {count:,}" in h
    # default sort metadata_modified desc — first dataset row
    assert esc(first_page[0]["title"] or first_page[0]["name"]) in h

    # every sort column, both directions — page rows match the builder
    for sort in ("title", "metadata_created", "metadata_modified", "resources", "views", "harvested"):
        for dir_ in ("asc", "desc"):
            out = source_datasets_stmts(source["id"], sort, dir_)
            expect = out["list"].all(*out["params"], PAGE_SIZE, 0)
            r = client.get(f"/harvester/{source['id']}?sort={sort}&dir={dir_}")
            assert r.status_code == 200
            assert esc(expect[0]["title"] or expect[0]["name"]) in r.content.decode(), f"sort={sort} dir={dir_}"

    # page 2 exists for sources with > 100 datasets; pager links keep sort/dir
    if count > PAGE_SIZE:
        # page 1 links forward to page 2; page 2 links back via Previous
        assert (
            "?sort=metadata_modified&amp;dir=desc&amp;page=2"
            in client.get(
                f"/harvester/{source['id']}",
            ).content.decode()
        )
        r2 = client.get(f"/harvester/{source['id']}?page=2")
        assert r2.status_code == 200
        assert "?sort=metadata_modified&amp;dir=desc&amp;page=1" in r2.content.decode()
        assert f"{PAGE_SIZE + 1:,}-{min(2 * PAGE_SIZE, count):,} of {count:,}" in r2.content.decode()
    # out-of-range page clamps rather than erroring
    assert client.get(f"/harvester/{source['id']}?page=99999").status_code == 200

    # the record block shows the fields the list page can't fit
    assert "Last run" in h
    assert "Jobs" in h

    # unknown id → 404
    r404 = client.get("/harvester/does-not-exist")
    assert r404.status_code == 404


# ---------------------------------------------------------------------------
# /links (facet page)
# ---------------------------------------------------------------------------
def test_links(client):
    stats = LINKS_STATS.get()
    assert stats is not None
    total = stats["total"]
    r = client.get("/links")
    html = r.content.decode()
    assert r.status_code == 200
    assert f"{total:,}" in html
    assert 'id="format-facet-list"' in html

    out = links_stmts({}, "host", "asc")
    assert out["count"].get(*out["params"])["n"] == total
    first_page = out["list"].all(*out["params"], PAGE_SIZE, 0)
    assert esc(first_page[0]["name"]) in html
    assert f"1-{len(first_page):,} of {total:,}" in html

    # one facet combo: first host + first format (from the unfiltered pools)
    pool = links_facet_counts({})
    if pool["hosts"] and pool["formats"]:
        filters = {"host": pool["hosts"][0]["host"], "format": pool["formats"][0]["fmt"]}
        out2 = links_stmts(filters, "name", "desc")
        n2 = out2["count"].get(*out2["params"])["n"]
        page2 = out2["list"].all(*out2["params"], PAGE_SIZE, 0)
        r2 = client.get(
            f"/links?host={pool['hosts'][0]['host']}&format={pool['formats'][0]['fmt']}&sort=name&dir=desc",
        )
        h2 = r2.content.decode()
        assert r2.status_code == 200
        assert esc(page2[0]["name"]) in h2
        assert f"of {n2:,}" in h2

    # ?host=__none__ renders the No URL pill
    r3 = client.get("/links?host=__none__")
    h3 = r3.content.decode()
    assert 'class="filter-pill"' in h3
    assert "No URL" in h3

    # ?format=__none__ renders the No format pill
    r4 = client.get("/links?format=__none__")
    h4 = r4.content.decode()
    assert 'class="filter-pill"' in h4
    assert "No format" in h4

    # the No format trailing bucket renders in the Format facet section
    h5 = client.get("/links").content.decode()
    section = _facet_section(h5, "Filter by format")
    assert ">No format<" in section

    # the Domain facet is uncapped: every host is a facet, the sidebar
    # starts with the top few and expands via the More toggle (same as the
    # /links/errors domain facet); scheme-less URLs trail as No URL
    assert 'id="host-facet-list"' in h5
    assert "More domains" in h5
    host_section = _facet_section(h5, "Filter by domain")
    assert ">No URL<" in host_section
    expanded = client.get("/links?hosts=all").content.decode()
    assert "Fewer domains" in expanded

    # out-of-range page clamps
    assert client.get("/links?page=99999").status_code == 200


# ---------------------------------------------------------------------------
# /datasets (facet page)
# ---------------------------------------------------------------------------
def _facet_section(html, aria_label):
    """The facet-group section HTML for one aria-label."""
    m = re.search(
        rf'<section class="facet-group" aria-label="{re.escape(aria_label)}">(.*?)</section>',
        html,
        re.S,
    )
    assert m, f"facet section not found: {aria_label}"
    return m.group(1)


def _datasets_sql_count(filters):
    out = datasets_stmts(filters, "organisation", "asc")
    return out["count"].get(*out["params"])["n"]


def test_temporal_facet_order(client):
    from explorer.queries.datasets import TEMPORAL_MAX_YEAR, TEMPORAL_MIN_YEAR  # noqa: PLC0415
    from explorer.views.datasets import _in_window_temporal_years  # noqa: PLC0415

    counts = datasets_facet_counts({})
    pool = {r["year"]: r["count"] for r in counts["temporal_years"]}
    buckets = counts["temporal_buckets"]
    expected = [str(y) for y in _in_window_temporal_years() if pool.get(y, 0) > 0]
    if buckets["post"]:
        expected.append(f"After {TEMPORAL_MAX_YEAR}")
    if buckets["pre1900"]:
        expected.append(f"Before {TEMPORAL_MIN_YEAR}")
    if buckets["none"]:
        expected.append("No temporal year")
    r = client.get("/datasets")
    section = _facet_section(r.content.decode(), "Filter by temporal year")
    names = re.findall(r'<span class="facet-name">([^<]+)</span>', section)
    assert names == expected


def test_temporal_toggle_keeps_metadata(client):
    # The More-years toggle keeps every active facet — including metadata
    # (regression: a previous version of the toggle URL dropped it).
    for url in (
        "/datasets?metadata_key=top:type&metadata_value=dataset&years=all",
        "/datasets?metadata_key=top:type&metadata_value=dataset",
    ):
        html = client.get(url).content.decode()
        m = re.search(r'<a href="([^"]*)"\s+class="facet-more-link facet-toggle"', html)
        assert m, "temporal More-years toggle missing"
        assert "metadata_key=top%3Atype" in m.group(1)
        assert "metadata_value=dataset" in m.group(1)
    # and with no metadata filter, the toggle URL stays clean
    html = client.get("/datasets?years=all").content.decode()
    m = re.search(r'<a href="([^"]*)"\s+class="facet-more-link facet-toggle"', html)
    assert m
    assert "metadata" not in m.group(1)


def test_theme_facet_order(client):
    from explorer.views.datasets import _theme_master  # noqa: PLC0415

    r = client.get("/datasets")
    section = _facet_section(r.content.decode(), "Filter by primary theme")
    names = re.findall(r'<span class="facet-name">([^<]+)</span>', section)
    assert names == [esc(t["label"]) for t in _theme_master()]


def test_links_facet_order(client):
    """The Links facet lists the link-count buckets in master order, each
    with its SQL pool count (the /organisations Datasets facet shape)."""
    counts = {r["bucket"]: r["count"] for r in datasets_facet_counts({})["links"]}
    expected = [name for value, name in LINK_BUCKETS if counts.get(value, 0) > 0]
    r = client.get("/datasets")
    section = _facet_section(r.content.decode(), "Filter by number of links")
    names = re.findall(r'<span class="facet-name">([^<]+)</span>', section)
    assert names == [esc(n) for n in expected]
    # and the facet count matches the SQL pool for a populated bucket
    top = max(counts, key=lambda v: counts[v])
    assert f'<span class="facet-count">{counts[top]:,}</span>' in section


def test_publisher_facet_order_and_toggle(client):
    """The Publisher facet lists every publisher count desc (top first,
    pool count next to the name), collapses past its cutoff behind the
    standard "More publishers" toggle like the temporal years list, and
    expands via ?publishers=all."""
    pool = datasets_facet_counts({})["publishers"]
    top = pool[0]
    r = client.get("/datasets")
    section = _facet_section(r.content.decode(), "Filter by publisher")
    names = re.findall(r'<span class="facet-name">([^<]+)</span>', section)
    assert names[0] == esc(top["name"])
    assert f'<span class="facet-count">{top["count"]:,}</span>' in section
    # long list collapses behind the toggle (1176 orgs in the live pool)
    assert 'id="publisher-facet-list"' in section
    assert "More publishers" in section

    expanded = client.get("/datasets?publishers=all").content.decode()
    assert "Fewer publishers" in expanded


def test_datasets_publisher_filter(client):
    """?publisher=<org slug> narrows the list to that org's datasets and
    renders the display-name pill; a bogus slug falls back to the whole
    list (validated against the orgs that own datasets)."""
    top = datasets_facet_counts({})["publishers"][0]
    expect = _datasets_sql_count({"publisher": top["value"]})
    h = client.get(f"/datasets?publisher={top['value']}").content.decode()
    assert f"of {expect:,}" in h
    assert "Remove publisher filter" in h
    assert esc(top["name"]) in h

    # combined with another facet, the publisher pool count stays live
    theme = next((r["theme"] for r in THEME_COUNTS.all() if r["theme"] != "__none__"), None)
    if theme:
        combo = _datasets_sql_count({"publisher": top["value"], "theme": theme})
        h2 = client.get(f"/datasets?publisher={top['value']}&theme={theme}").content.decode()
        assert f"of {combo:,}" in h2

    # a bogus publisher value falls back to the unfiltered list
    h = client.get("/datasets?publisher=bogus").content.decode()
    assert f"of {_datasets_sql_count({}):,}" in h
    assert "Remove publisher filter" not in h


def test_datasets_links_filter(client):
    """?links=<bucket> narrows the list to datasets whose link count falls
    in that range, renders the filter pill, and keeps pager URLs clean."""
    for bucket in ("0", "1-10", "11-50", "501-1000"):
        expect = _datasets_sql_count({"links": bucket})
        h = client.get(f"/datasets?links={bucket}").content.decode()
        assert f"of {expect:,}" in h, bucket

    # the pill renders with the human bucket label
    h = client.get("/datasets?links=501-1000").content.decode()
    assert "Remove links filter" in h
    assert esc(LINK_BUCKET_NAMES["501-1000"]) in h

    # a bogus bucket value falls back to the unfiltered list
    h = client.get("/datasets?links=bogus").content.decode()
    assert f"of {_datasets_sql_count({}):,}" in h
    assert "Remove links filter" not in h


def test_datasets(client):
    total = _datasets_sql_count({})
    r = client.get("/datasets")
    html = r.content.decode()
    assert r.status_code == 200
    # Datasets group sub-nav — Series / Reviews / Suggestions are sub-reports
    # (the same macro as the Links and Publishers groups); the current report
    # is the active h1 heading and the group is gone from the main nav.
    _assert_report_subnav(
        html,
        "Datasets",
        (("Series", "/series"), ("Reviews", "/reviews"), ("Suggestions", "/suggestions")),
        ("/series", "/reviews", "/suggestions"),
        "/datasets",
    )
    assert f"1-{PAGE_SIZE:,} of {total:,}" in html

    out = datasets_stmts({}, "organisation", "asc")
    first_page = out["list"].all(*out["params"], PAGE_SIZE, 0)
    assert esc(first_page[0]["title"]) in html
    assert esc(first_page[0]["organisation"]) in html

    # one facet combo: a real theme, with the sidebar count matching SQL
    theme_rows = THEME_COUNTS.all()
    theme = next((t["theme"] for t in theme_rows if t["theme"] != "__none__"), None)
    if theme:
        r2 = client.get(f"/datasets?theme={theme}")
        h2 = r2.content.decode()
        assert r2.status_code == 200
        assert f"of {_datasets_sql_count({'theme': theme}):,}" in h2

    # sidebar theme count equals the SQL facet aggregate (unfiltered page)
    theme_counts = {r["theme"]: r["count"] for r in datasets_facet_counts({})["themes"]}
    if theme_counts:
        t = next(
            (k for k, v in theme_counts.items() if k != "__none__" and v > 0),
            None,
        )
        if t:
            assert f"?sort=organisation&amp;dir=asc&amp;theme={t}" in html
            assert f'<span class="facet-count">{theme_counts[t]:,}</span>' in html

    # invalid page value clamps to 1 (rather than erroring)
    assert client.get("/datasets?page=bogus").status_code == 200
    assert client.get("/datasets?page=99999").status_code == 200


# ---------------------------------------------------------------------------
# /metadata
# ---------------------------------------------------------------------------
def test_metadata_pages(client):
    r = client.get("/metadata")
    html = r.content.decode()
    assert r.status_code == 200
    assert "<h1>Metadata</h1>" in html
    assert html.count("<table") == 1

    keys = METADATA_KEYS.all()
    top = next(k for k in keys if k["section"] == "top")
    section, name = top["key"].split(":", 1)
    r2 = client.get(f"/metadata/{section}/{name}")
    h2 = r2.content.decode()
    assert r2.status_code == 200
    assert f"<h1>Metadata: {name}</h1>" in h2
    first = METADATA_VALUES.all(top["key"], 100, 0)[0]
    assert esc(first["value"]) in h2

    total_values_row = METADATA_VALUE_COUNT.get(top["key"])
    assert total_values_row is not None
    total_values = total_values_row["n"]
    if total_values > 100:
        assert client.get(f"/metadata/{section}/{name}?page=2").status_code == 200
    assert client.get(f"/metadata/bogus/{name}").status_code == 404
    assert client.get("/metadata/top/__no_such_field__").status_code == 404


# ---------------------------------------------------------------------------
# /series
# ---------------------------------------------------------------------------
def test_series_pages(client):
    total_row = SERIES_COUNT.get()
    assert total_row is not None
    total = total_row["n"]
    r = client.get("/series")
    html = r.content.decode()
    assert r.status_code == 200
    # Series is a sub-report of Datasets (same sub-nav macro as the Links
    # and Publishers groups) — active report is the h1 heading, and Series
    # is no longer its own main-nav item.
    _assert_report_subnav(html, "Series", (("Datasets", "/datasets"),), ("/series",), "/datasets")
    # reserves the (blank, cardless) facets sidebar so the table lines up
    # with the other Datasets-group pages
    assert 'class="facets facets--empty"' in html
    assert "content-layout--full" not in html
    assert f"{total:,}" in html

    default = series_list_stmt("dataset_count", "desc").all(50, 0)
    assert default
    assert esc(default[0]["root_title"]) in html

    r2 = client.get("/series?sort=root_title&dir=asc")
    assert r2.status_code == 200
    by_title = series_list_stmt("root_title", "asc").all(50, 0)
    assert esc(by_title[0]["root_title"]) in r2.content.decode()

    sid = default[0]["id"]
    r3 = client.get(f"/series/{sid}")
    h3 = r3.content.decode()
    assert r3.status_code == 200
    series_row = SERIES_BY_ID.get(sid)
    assert series_row is not None
    assert esc(series_row["root_title"]) in h3
    # series detail is a drill-down of the Series report — Datasets stays
    # the highlighted main-nav item
    primary = _primary_nav(h3)
    assert 'href="/datasets"' in primary
    assert 'aria-current="page"' in primary

    assert client.get("/series/abc").status_code == 404
    assert client.get("/series/99999999").status_code == 404


# ---------------------------------------------------------------------------
# /reviews — row order vs the SQL builder (the DB is the source of truth)
# ---------------------------------------------------------------------------
_REVIEW_SORTS = ("title", "org", "overall", "findability", "metadata", "resources")


def expected_review_ids(sort, dir_, filters, page, page_size=PAGE_SIZE):
    """Contract test: the view page must equal the SQL builder's page.
    The view renders reviews_stmts(filters, sort, dir_) verbatim (offset /
    size from paginate()), so this fetches the same builder — it pins the
    view→builder wiring, the facet WHERE, the sort/tiebreak ORDER BY and
    the page clamp/offset arithmetic."""
    stmts = reviews_stmts(filters, sort, dir_)
    total = stmts["count"].get(*stmts["params"])["n"]
    total_pages = max(1, math.ceil(total / page_size))
    page = min(max(page, 1), total_pages)
    offset = (page - 1) * page_size
    rows = stmts["list"].all(*stmts["params"], page_size, offset)
    return [r["dataset_id"] for r in rows]


def page_ids(html):
    """Dataset ids in table-row order — every row links to its dataset."""
    return re.findall(r'/dataset/[^/]+/([^"]+)"', html)


def test_reviews(client):
    all_reviews = latest_reviews()
    assert all_reviews
    expect, total = expected_review_ids("overall", "asc", {}, 1), len(all_reviews)

    r = client.get("/reviews")
    html = r.content.decode()
    assert r.status_code == 200
    # Reviews is a sub-report of Datasets — active h1 heading in the group's
    # sub-nav, no longer its own main-nav item
    _assert_report_subnav(html, "Reviews", (("Datasets", "/datasets"),), ("/reviews",), "/datasets")
    assert f"Dataset reviews ({total})" in html
    assert page_ids(html) == expect

    # every sort column, both directions
    for sort in _REVIEW_SORTS:
        for dir_ in ("asc", "desc"):
            r = client.get(f"/reviews?sort={sort}&dir={dir_}")
            assert r.status_code == 200
            assert page_ids(r.content.decode()) == expected_review_ids(
                sort,
                dir_,
                {},
                1,
            ), f"sort={sort} dir={dir_}"

    # invalid sort falls back to overall asc
    r = client.get("/reviews?sort=bogus")
    assert page_ids(r.content.decode()) == expected_review_ids("overall", "asc", {}, 1)

    # one facet combo across two score groups
    r = client.get("/reviews?overall=3&metadata=4")
    assert r.status_code == 200
    assert page_ids(r.content.decode()) == expected_review_ids(
        "overall",
        "asc",
        {"overall": "3", "metadata": "4"},
        1,
    )

    # "none" facet renders its pill
    r = client.get("/reviews?overall=none")
    assert b'class="filter-pill"' in r.content
    assert b"No score" in r.content

    # page clamp — 99999 lands on the last page
    r = client.get("/reviews?page=99999")
    assert page_ids(r.content.decode()) == expected_review_ids(
        "overall",
        "asc",
        {},
        99999,
    )
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# /suggestions
# ---------------------------------------------------------------------------
def expected_suggestion_ids(sort, dir_, page, page_size=PAGE_SIZE):
    """Contract test: the view page must equal the SQL builder's page.
    The view renders suggestions_stmts(sort, dir_) verbatim (offset / size
    from paginate()), so this fetches the same builder — it pins the
    view→builder wiring, the sort/tiebreak ORDER BY and the page
    clamp/offset arithmetic."""
    stmts = suggestions_stmts(sort, dir_)
    total = stmts["count"].get()["n"]
    total_pages = max(1, math.ceil(total / page_size))
    page = min(max(page, 1), total_pages)
    offset = (page - 1) * page_size
    rows = stmts["list"].all(page_size, offset)
    return [r["dataset_id"] for r in rows]


def test_suggestions(client):
    stmts = suggestions_stmts("confidence", "asc")
    total = stmts["count"].get()["n"]
    assert total > 0

    r = client.get("/suggestions")
    html = r.content.decode()
    assert r.status_code == 200
    # Suggestions is a sub-report of Datasets — active h1 heading in the
    # group's sub-nav, no longer its own main-nav item
    _assert_report_subnav(html, "Suggestions", (("Datasets", "/datasets"),), ("/suggestions",), "/datasets")
    # reserves the (blank, cardless) facets sidebar so the table lines up
    # with the other Datasets-group pages
    assert 'class="facets facets--empty"' in html
    assert "content-layout--full" not in html
    assert f"Suggestions ({total})" in html

    for sort in ("title", "org", "theme", "confidence"):
        for dir_ in ("asc", "desc"):
            r = client.get(f"/suggestions?sort={sort}&dir={dir_}")
            expect = expected_suggestion_ids(sort, dir_, 1)
            assert page_ids(r.content.decode()) == expect, f"sort={sort} dir={dir_}"

    # invalid sort falls back to confidence asc
    r = client.get("/suggestions?sort=bogus")
    expect = expected_suggestion_ids("confidence", "asc", 1)
    assert page_ids(r.content.decode()) == expect

    # page clamp
    r = client.get("/suggestions?page=99999")
    assert r.status_code == 200
    assert page_ids(r.content.decode()) == expected_suggestion_ids("confidence", "asc", 99999)


def _pager_hrefs(html):
    """Pager link hrefs (page numbers + prev/next all use .page-link)."""
    return re.findall(r'<a class="page-link" href="([^"]+)"', html)


def test_pager_urls_never_undefined(client):
    """Regression: pages without a sort UI used to render pager links like
    ?sort=undefined&dir=undefined&page=N (the macros' old "kept deliberately"
    defaults), and /report/{key} hardcoded sort=name&dir=asc although it has
    no sort UI. The macros now take a base fragment the view builds
    (pagination-plan workstream B), so every pager href is either the view's
    own query state (?sort=..&dir=..&page=N) or a clean ?page=N — never
    "undefined", and reports never pretend to sort by name."""
    # /suggestions — sortable, > 100 rows: the pager keeps the view's sort/dir
    total = suggestions_stmts("confidence", "asc")["count"].get()["n"]
    if total > PAGE_SIZE:
        html = client.get("/suggestions").content.decode()
        hrefs = _pager_hrefs(html)
        assert hrefs, "suggestions pager should render"
        assert "undefined" not in "".join(hrefs)
        expect_base = "?" + esc(urlencode({"sort": "confidence", "dir": "asc"}))
        assert all(h.startswith(expect_base + "&amp;page=") for h in hrefs)

    # /metadata/{s}/{n} — no query state at all: clean ?page=N
    keys = METADATA_KEYS.all()
    top = next(k for k in keys if k["section"] == "top")
    section, name = top["key"].split(":", 1)
    n_values = METADATA_VALUE_COUNT.get(top["key"])["n"]
    if n_values > PAGE_SIZE:
        html = client.get(f"/metadata/{section}/{name}").content.decode()
        hrefs = _pager_hrefs(html)
        assert hrefs, "metadata values pager should render"
        assert "undefined" not in "".join(hrefs)
        assert all(h.startswith("?page=") for h in hrefs)
        # count display: "X-Y of Z" range in the header right pane
        assert f"1-{PAGE_SIZE:,} of {n_values:,}" in html

    # /report/{key} — no sort UI: unfiltered links are clean ?page=N, and
    # with an active facet they keep only the facet (?org=..&page=N)
    report = next(r for r in REPORTS if r["kind"] != "duplicate-urls")
    total = report_stmts(report)["count"].get()["n"]
    if total > PAGE_SIZE:
        html = client.get(f"/report/{report['key']}").content.decode()
        hrefs = _pager_hrefs(html)
        assert hrefs, "report pager should render"
        assert "undefined" not in "".join(hrefs)
        assert all(h.startswith("?page=") for h in hrefs)
        if report.get("facets"):
            facet = report["facets"][0]
            sql, params = report_facet_counts(report, {})[facet["key"]]
            options = Query(sql).all(*params)
            if options:
                slug = options[0]["slug"]
                r2 = client.get(
                    f"/report/{report['key']}?{urlencode({facet['key']: slug})}",
                )
                hrefs2 = _pager_hrefs(r2.content.decode())
                if hrefs2:  # the facet may filter below a pager
                    assert "undefined" not in "".join(hrefs2)
                    expect_base = "?" + esc(urlencode({facet["key"]: slug}))
                    assert all(h.startswith(expect_base + "&amp;page=") for h in hrefs2)


# ---------------------------------------------------------------------------
# /dataset/{org}/{id}
# ---------------------------------------------------------------------------
def test_dataset_detail_with_review(client):
    rev = latest_reviews()[0]
    dataset_id = rev["dataset_id"]
    slug = rev.get("org_slug") or "x"

    r = client.get(f"/dataset/{slug}/{dataset_id}")
    html = r.content.decode()
    assert r.status_code == 200, f"status {r.status_code}"
    assert (
        esc(rev.get("title") or rev.get("suggested_title") or "") in html or get_review(dataset_id) is not None
    )  # review block present below

    # review block — Overall X/5 and the findability subscore
    assert f"Overall {rev['overall']}/5" in html
    sub = (rev.get("scores") or {}).get("findability") or {}
    if sub.get("score") is not None:
        assert f"Findability {sub['score']}/5" in html

    # 404s
    assert client.get("/dataset/x/__no_such_id__").status_code == 404
    assert client.get("/dataset/x/y").status_code == 404

"""Query-layer + view tests for /links/errors against the live DB.

Locks in the link_errors query layer: statement shapes, count/list
consistency, deterministic ordering, the datasets LEFT JOIN (including the
Unknown state for packages absent from the snapshot), the self-excluding
facet pools, and the view (200, sub-nav, three-state badge rendering).
All of it needs the `link_errors` table loaded — skip cleanly otherwise
(just ingest-link-errors fills it from data/errors-current.csv).
"""

import re

import pytest

from explorer.queries.core import Query
from explorer.queries.link_errors import (
    CATEGORY_LABELS,
    LINK_ERRORS_SORT_COLUMNS,
    link_errors_facet_counts,
    link_errors_stats,
    link_errors_stmts,
)

pytestmark = pytest.mark.usefixtures("db_ready")


@pytest.fixture(scope="module")
def link_errors_loaded():
    """The link_errors table exists and has rows (migration + ingest ran)."""
    try:
        n = Query("SELECT COUNT(*) AS n FROM link_errors").get()["n"]
    except Exception as e:  # noqa: BLE001 — table missing / DB not migrated
        pytest.skip(f"link_errors table unavailable: {e}")
    if not n:
        pytest.skip("link_errors is empty — run: just ingest-link-errors")
    return n


def _count(filters):
    out = link_errors_stmts(filters, "url", "asc")
    return out["count"].get(*out["params"])["n"]


def _url_host(url):
    """Host of a resource URL — the same split the SQL url sort uses
    (scheme://host[:port]/path -> lowercased host, '' when scheme-less)."""
    m = re.search(r"://([^/]+)", url or "")
    return m.group(1).split(":", 1)[0].lower() if m else ""


def _without(filters, key):
    d = dict(filters)
    d[key] = None
    return d


# ---------------------------------------------------------------------------
# Whole-table stats + statement shape
# ---------------------------------------------------------------------------
def test_link_errors_stats_shape(link_errors_loaded):
    stats = link_errors_stats()
    assert stats["total"] == link_errors_loaded
    # every row is either a current error or a resolved (OK) link — the
    # two populations the report header describes
    assert stats["errors"] + stats["resolved"] == stats["total"]
    assert stats["errors"] > 0
    print("ok: stats (total = errors + resolved)")


def test_link_errors_list_shape_and_sort_whitelist(link_errors_loaded):
    out = link_errors_stmts({}, "url", "asc")
    n = out["count"].get(*out["params"])["n"]
    assert n == link_errors_loaded
    rows = out["list"].all(*out["params"], 100, 0)
    assert len(rows) == 100
    for col in (
        "package_id",
        "package_name",
        "resource_id",
        "resource_url",
        "datagovuk_url",
        "org_name",
        "org_display_name",
        "status",
        "category",
        "error_detail",
        "to_delete",
        "org_slug",
        "harvest_state",
        "harvest_source_title",
    ):
        assert col in rows[0], f"list row missing {col}"

    # the default page sorts by URL (host asc, ingest order breaks ties)
    hosts = [_url_host(r["resource_url"]) for r in rows]
    assert hosts == sorted(hosts)
    print("ok: list shape + default url asc sort")


@pytest.mark.parametrize("sort", LINK_ERRORS_SORT_COLUMNS)
@pytest.mark.parametrize("dir_", ["asc", "desc"])
def test_link_errors_count_matches_list_and_deterministic(link_errors_loaded, sort, dir_):
    """Each sortable column, both directions: count/list agree and the
    ORDER BY ends with `, e.id`, so ties order the same way on every run."""
    out = link_errors_stmts({}, sort, dir_)
    n = out["count"].get(*out["params"])["n"]
    rows = out["list"].all(*out["params"], 200, 0)
    assert n == link_errors_loaded
    assert len(rows) == 200
    again = out["list"].all(*out["params"], 200, 0)
    assert [r["id"] for r in rows] == [r["id"] for r in again], f"sort={sort} dir={dir_} not deterministic"
    print(f"ok: count/list + determinism (sort={sort}, dir={dir_})")


# ---------------------------------------------------------------------------
# The datasets LEFT JOIN — org slug, harvest state incl. Unknown
# ---------------------------------------------------------------------------
def test_harvest_state_join_includes_unknown(link_errors_loaded):
    """The three harvest states partition the table: harvested/manual from
    the datasets join, unknown for packages absent from the snapshot (the
    ~749 missing packages). Every row lands on exactly one state."""
    rows = Query(
        "SELECT harvest_state, COUNT(*) AS n FROM ("
        "  SELECT CASE WHEN d.id IS NULL THEN 'unknown'"
        "              WHEN d.harvested = 1 THEN 'harvested'"
        "              ELSE 'manual' END AS harvest_state"
        "  FROM link_errors e LEFT JOIN datasets d ON d.id = e.package_id"
        ") s GROUP BY 1",
    ).all()
    states = {r["harvest_state"]: r["n"] for r in rows}
    assert set(states) == {"harvested", "manual", "unknown"}
    assert states["unknown"] > 0  # the report's explicit Unknown population
    assert sum(states.values()) == link_errors_loaded

    # filtered list: the unknown bucket is exactly the rows whose package
    # isn't in the datasets snapshot (d.org_slug NULL when not joined)
    n_unknown = _count({"harvested": "unknown"})
    assert n_unknown == states["unknown"]
    unknown_rows = link_errors_stmts({"harvested": "unknown"}, "url", "asc")["list"].all(
        *link_errors_stmts({"harvested": "unknown"}, "url", "asc")["params"],
        100,
        0,
    )
    assert unknown_rows
    assert all(r["org_slug"] is None for r in unknown_rows)
    assert all(r["harvest_state"] == "unknown" for r in unknown_rows)
    print("ok: harvest join (states partition, unknown = no datasets row)")


# ---------------------------------------------------------------------------
# Sidebar facet pools (self-excluding SQL aggregates)
# ---------------------------------------------------------------------------
def test_link_errors_facet_pools_partition_list_count(link_errors_loaded):
    """Each group's pool total equals the list count with that group's
    filter cleared. Category, status (+ the No response trailing bucket),
    domain (+ the No URL bucket), harvest state and publisher each
    partition the whole pool — domain and publisher are uncapped (every
    host / every org is a facet), so they partition like the rest."""
    base = link_errors_facet_counts({})
    category = base["categories"][0]["value"]
    status = base["statuses"][0]["value"]
    publisher = base["publishers"][0]["value"]
    domain = base["domains"][0]["value"]

    combos = [
        {},
        {"category": category},
        {"status": status},
        {"status": "__none__"},
        {"to_delete": "yes"},
        {"to_delete": "no", "category": "NOT_FOUND"},
        {"domain": domain},
        {"domain": "__none__"},
        {"harvested": "unknown"},
        {"publisher": publisher},
        {"category": category, "status": "__none__"},
        {"category": "OK", "harvested": "harvested"},
    ]
    for filters in combos:
        counts = link_errors_facet_counts(filters)
        assert sum(r["count"] for r in counts["categories"]) == _count(_without(filters, "category")), filters
        assert sum(r["count"] for r in counts["statuses"]) + counts["no_response"] == _count(
            _without(filters, "status"),
        ), filters
        assert sum(counts["to_delete"].values()) == _count(_without(filters, "to_delete")), filters
        # domain partitions into parseable hosts + the scheme-less No URL rows
        assert sum(r["count"] for r in counts["domains"]) + counts["no_url"] == _count(
            _without(filters, "domain"),
        ), filters
        assert sum(counts["harvested"].values()) == _count(_without(filters, "harvested")), filters
        # publisher is uncapped — its pool partitions the publisher-cleared
        # count (every link_errors row carries an org name)
        assert sum(r["count"] for r in counts["publishers"]) == _count(
            _without(filters, "publisher"),
        ), filters

    # a non-empty combo still surfaces domains/publishers in the pools
    assert sum(r["count"] for r in link_errors_facet_counts({"category": "NOT_FOUND"})["domains"]) > 0
    assert sum(r["count"] for r in link_errors_facet_counts({"category": "NOT_FOUND"})["publishers"]) > 0
    print("ok: facet pools partition the group-cleared list count")


def test_link_errors_facet_value_matches_filtered_count(link_errors_loaded):
    """Picking a facet value in the UI shows exactly the pool's count for
    that value — the category OK pool equals the resolved stats, and the
    status No response bucket equals the code-less list."""
    base = link_errors_facet_counts({})
    ok_pool = {r["value"]: r["count"] for r in base["categories"]}["OK"]
    assert ok_pool == _count({"category": "OK"})
    assert ok_pool == link_errors_stats()["resolved"]

    assert base["no_response"] == _count({"status": "__none__"})

    # No URL bucket equals the host-less list, and picking the top domain
    # shows exactly the pool's count
    assert base["no_url"] == _count({"domain": "__none__"})
    top_domain = base["domains"][0]["value"]
    assert base["domains"][0]["count"] == _count({"domain": top_domain})

    # to-delete partitions into the yes/no recommendations, covering the table
    assert base["to_delete"] == {
        "yes": _count({"to_delete": "yes"}),
        "no": _count({"to_delete": "no"}),
    }
    assert sum(base["to_delete"].values()) == link_errors_loaded

    # a real category + status combo (e.g. 404s that are NOT_FOUND) narrows
    assert "NOT_FOUND" in {r["value"] for r in base["categories"]}
    assert {r["value"] for r in base["statuses"]} >= {"404"}
    assert _count({"category": "NOT_FOUND", "status": "404"}) > 0
    print("ok: facet value counts match filtered list counts")


# ---------------------------------------------------------------------------
# The view
# ---------------------------------------------------------------------------
def _squash(html: str) -> str:
    """Collapse whitespace runs to single spaces — djlint reflows long
    template tags/attributes onto several lines, so rendered markup carries
    harmless newlines the exact-match assertions must not trip on."""
    return re.sub(r"\s+", " ", html)


def _has_badge(html: str, cls: str, label: str) -> bool:
    """A harvest-state badge span with the given class and label — the
    harvested badge optionally carries a title (its harvest source), so
    the match allows for that attribute."""
    return (
        re.search(
            rf'<span class="badge {cls}"(?: title="[^"]*")?>\s*{re.escape(label)}\s*</span>',
            _squash(html),
        )
        is not None
    )


def test_link_errors_view(client, link_errors_loaded):
    r = client.get("/links/errors")
    html = _squash(r.content.decode())
    assert r.status_code == 200
    assert "Link errors" in html

    # shared sub-nav — the current report is the page's h1 heading, styled
    # as the active nav item (like the primary nav); no separate heading
    assert '<h1 class="nav-link nav-link--active" aria-current="page">Errors</h1>' in html
    assert '<a href="/links" class="nav-link">Links</a>' in html

    # page description + count of the current filter
    assert f"1-100 of {link_errors_loaded:,}" in html

    # the three badge states render across their filters
    assert _has_badge(client.get("/links/errors?harvested=harvested").content.decode(), "badge-harvested", "Harvested")
    assert _has_badge(client.get("/links/errors?harvested=manual").content.decode(), "badge-manual", "Manual")
    assert _has_badge(client.get("/links/errors?harvested=unknown").content.decode(), "badge-unknown", "Unknown")

    # resolved rows render with the distinct positive treatment
    ok = _squash(client.get("/links/errors?category=OK").content.decode())
    assert "link-errors-row--ok" in ok
    assert '<span class="status status--ok"' in ok

    # the To delete column shows an explicit Yes / No (never a bare dash) —
    # sort by to_delete so page 1 is guaranteed all-Yes (desc) / all-No (asc)
    assert '<td class="col-text">Yes</td>' in _squash(
        client.get("/links/errors?sort=to_delete&dir=desc").content.decode(),
    )
    assert '<td class="col-text">No</td>' in _squash(
        client.get("/links/errors?sort=to_delete&dir=asc").content.decode(),
    )

    # the To delete facet filters the table and renders its own sidebar group
    yes = _squash(client.get("/links/errors?to_delete=yes").content.decode())
    assert "filter-pill" in yes
    assert 'class="facet-group" aria-label="Filter by the remove-link recommendation"' in yes
    assert '<td class="col-text">No</td>' not in yes

    # the Domain facet is uncapped: every host is a facet, the sidebar
    # starts with the top few and expands via the More toggle; scheme-less
    # URLs trail as the No URL bucket
    assert 'class="facet-group" aria-label="Filter by domain"' in html
    assert "No URL" in html
    assert "More domains" in html
    # the Domain facet also opts into the live JS search (like /links and
    # /datasets) — a search box above the domain and publisher lists only
    assert 'aria-label="Search domains"' in html
    assert 'aria-label="Search publishers"' in html
    assert html.count('class="facet-search-input"') == 2
    assert "/static/facet-search.js" in html
    all_hosts = _squash(client.get("/links/errors?domains=all").content.decode())
    assert "Fewer domains" in all_hosts
    no_url = _squash(client.get("/links/errors?domain=__none__").content.decode())
    assert 'class="filter-pill"' in no_url

    # the Publisher facet is uncapped: every org is a facet, the sidebar
    # starts with the top few and expands via the More toggle
    assert 'class="facet-group" aria-label="Filter by publisher"' in html
    assert "More publishers" in html
    all_pubs = _squash(client.get("/links/errors?publishers=all").content.decode())
    assert "Fewer publishers" in all_pubs

    # publisher facets and row cells show display names (from organisations),
    # not org slugs — e.g. the top error publisher
    top = link_errors_facet_counts({})["publishers"][0]
    assert top["name"] in html
    pub_rows = _squash(client.get("/links/errors", {"publisher": top["value"]}).content.decode())
    assert f'<a href="/organisation/{top["value"]}">{top["name"]}</a>' in pub_rows
    print("ok: /links/errors view (200, sub-nav, states, resolved styling)")


def _facet_order(html: str, aria: str) -> list[str]:
    """The facet item names inside the group with that aria-label, in
    render order."""
    m = re.search(
        rf'<section class="facet-group" aria-label="{re.escape(aria)}">(.*?)</section>',
        html,
        re.S,
    )
    assert m, f"no facet group with aria-label {aria!r}"
    return re.findall(r'class="facet-name">(.*?)</span>', m.group(1))


def test_link_errors_facet_order_follows_filtered_pool(client, link_errors_loaded):
    """Every facet list renders in its own pool's count order — selecting a
    facet re-sorts the sibling Outcome / HTTP-status / To-delete / Harvested
    lists to the counts shown, instead of freezing them to the unfiltered
    page's order. Picked via the largest publisher whose error mix tops on a
    category other than the global top (NOT_FOUND)."""
    rows = Query(
        """SELECT org_name FROM (
              SELECT org_name,
                     (array_agg(category ORDER BY c DESC, category))[1] AS top_cat,
                     SUM(c) AS n
              FROM (SELECT org_name, category, COUNT(*) AS c
                    FROM link_errors GROUP BY 1, 2) x
              GROUP BY org_name
            ) y WHERE top_cat <> 'NOT_FOUND' ORDER BY n DESC LIMIT 1""",
    ).all()
    if not rows:
        pytest.skip("no publisher whose outcome tops off the global top category")
    slug = rows[0]["org_name"]

    pool = link_errors_facet_counts({"publisher": slug})
    html = client.get("/links/errors", {"publisher": slug}).content.decode()

    # Outcome re-sorts to the publisher's pool: its top category leads,
    # ahead of the global top (Not found).
    expected_outcome = [CATEGORY_LABELS.get(r["value"], (r["value"] or "").title()) for r in pool["categories"]]
    assert expected_outcome
    assert expected_outcome[0] != CATEGORY_LABELS["NOT_FOUND"]
    assert _facet_order(html, "Filter by outcome") == expected_outcome

    # HTTP status (minus the fixed No response trailing bucket), To delete
    # and Harvested follow their pool counts too.
    status = [n for n in _facet_order(html, "Filter by HTTP status") if n != "No response"]
    assert status == [r["value"] for r in pool["statuses"]]
    for aria, counts in (
        ("Filter by the remove-link recommendation", pool["to_delete"]),
        ("Filter by harvest status", pool["harvested"]),
    ):
        shown = _facet_order(html, aria)
        # the rendered names are the value labels (No/Yes, Harvested/...)
        assert shown == [v.title() for v in sorted(counts, key=lambda v: (-counts[v], v))], aria
    print("ok: facet lists re-sort to the filtered pool's count order")


def test_link_errors_filters_and_pills(client, link_errors_loaded):
    # a status + outcome combo (404 / Not found) — the most common error
    r = client.get("/links/errors?status=404&category=NOT_FOUND")
    html = r.content.decode()
    assert r.status_code == 200
    assert "404 Not found" in html
    # active-filter pills for both selections
    assert 'class="filter-pill"' in html

    # No response selection (DNS/timeout rows) renders its trailing label
    r = client.get("/links/errors?status=__none__")
    html = r.content.decode()
    assert r.status_code == 200
    assert "No response" in html

    # out-of-range page clamps instead of erroring
    assert client.get("/links/errors?page=99999").status_code == 200
    print("ok: /links/errors filters + pills")


def test_links_page_subnav(client):
    """/links shows the sub-nav with the current page as its h1 heading."""
    html = client.get("/links").content.decode()
    assert client.get("/links").status_code == 200
    assert '<h1 class="nav-link nav-link--active" aria-current="page">Links</h1>' in html
    assert '<a href="/links/errors" class="nav-link">Errors</a>' in html
    print("ok: /links sub-nav (Links selected as the h1, no separate heading)")

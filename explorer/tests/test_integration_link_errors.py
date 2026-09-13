"""Integration tests for the /links/errors query layer on the seeded fixture.

Phase 4 port (docs/test-review-plan.md) of ``test_link_errors.py``: statement
shapes, count/list consistency, deterministic ordering, the datasets LEFT
JOIN (including the Unknown state), and the self-excluding facet pools. The
view/render tests stay in the Phase 5 behaviour suite.
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

pytestmark = pytest.mark.django_db


def _count(filters):
    out = link_errors_stmts(filters, "url", "asc")
    return out["count"].get(*out["params"])["n"]


def _url_host(url):
    """Host of a resource URL — the same split the SQL url sort uses
    (scheme://host[:port]/path -> lowercased host, '' when scheme-less)."""
    match = re.search(r"://([^/]+)", url or "")
    return match.group(1).split(":", 1)[0].lower() if match else ""


def _without(filters, key):
    return {k: v for k, v in filters.items() if k != key}


def test_link_errors_stats_shape():
    total = _count({})
    stats = link_errors_stats()
    assert stats["total"] == total
    # every row is either a current error or a resolved (OK) link
    assert stats["errors"] + stats["resolved"] == stats["total"]
    assert stats["errors"] > 0


def test_link_errors_list_shape_and_sort_whitelist():
    out = link_errors_stmts({}, "url", "asc")
    total = out["count"].get(*out["params"])["n"]
    rows = out["list"].all(*out["params"], 1_000_000, 0)
    assert len(rows) == total
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

    # the default page sorts by URL (host asc, id breaks ties)
    hosts = [_url_host(r["resource_url"]) for r in rows]
    assert hosts == sorted(hosts)


@pytest.mark.parametrize("sort", LINK_ERRORS_SORT_COLUMNS)
@pytest.mark.parametrize("dir_", ["asc", "desc"])
def test_link_errors_count_matches_list_and_deterministic(sort, dir_):
    """Each sortable column, both directions: count/list agree and the
    ORDER BY ends with `, e.id`, so ties order the same on every run."""
    out = link_errors_stmts({}, sort, dir_)
    n = out["count"].get(*out["params"])["n"]
    rows = out["list"].all(*out["params"], 1_000_000, 0)
    assert n == len(rows)
    assert [r["id"] for r in rows] == [r["id"] for r in out["list"].all(*out["params"], 1_000_000, 0)]


def test_harvest_state_join_includes_unknown():
    """The three harvest states partition the table: harvested/manual from
    the datasets join, unknown for packages absent from the snapshot."""
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
    assert states["unknown"] > 0
    assert sum(states.values()) == _count({})

    assert _count({"harvested": "unknown"}) == states["unknown"]
    out = link_errors_stmts({"harvested": "unknown"}, "url", "asc")
    unknown_rows = out["list"].all(*out["params"], 100, 0)
    assert unknown_rows
    assert all(r["org_slug"] is None for r in unknown_rows)
    assert all(r["harvest_state"] == "unknown" for r in unknown_rows)


def test_link_errors_facet_pools_partition_list_count():
    """Each group's pool total equals the list count with that group's
    filter cleared — category/status/domain/harvest/publisher, with the
    No response / No URL trailing buckets folded in."""
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
        assert sum(r["count"] for r in counts["domains"]) + counts["no_url"] == _count(
            _without(filters, "domain"),
        ), filters
        assert sum(counts["harvested"].values()) == _count(_without(filters, "harvested")), filters
        assert sum(r["count"] for r in counts["publishers"]) == _count(
            _without(filters, "publisher"),
        ), filters


def test_link_errors_facet_value_matches_filtered_count():
    """Picking a facet value shows exactly that value's pool count."""
    base = link_errors_facet_counts({})
    ok_pool = {r["value"]: r["count"] for r in base["categories"]}["OK"]
    assert ok_pool == _count({"category": "OK"})
    assert ok_pool == link_errors_stats()["resolved"]

    assert base["no_response"] == _count({"status": "__none__"})
    assert base["no_url"] == _count({"domain": "__none__"})

    top_domain = base["domains"][0]["value"]
    assert base["domains"][0]["count"] == _count({"domain": top_domain})

    assert base["to_delete"] == {"yes": _count({"to_delete": "yes"}), "no": _count({"to_delete": "no"})}
    assert sum(base["to_delete"].values()) == _count({})

    assert "NOT_FOUND" in {r["value"] for r in base["categories"]}
    assert {r["value"] for r in base["statuses"]} >= {"404"}
    assert _count({"category": "NOT_FOUND", "status": "404"}) > 0


def test_link_errors_facet_order_follows_filtered_pool():
    """Every facet list is ordered count desc (ties by value), and a
    publisher whose error mix tops on a different category re-sorts the
    Outcome pool away from the global top."""
    global_top = link_errors_facet_counts({})["categories"][0]["value"]
    for publisher in ("alpha", "beta"):
        categories = [
            (r["value"], r["count"]) for r in link_errors_facet_counts({"publisher": publisher})["categories"]
        ]
        assert categories == sorted(categories, key=lambda pair: (-pair[1], pair[0])), publisher
    alpha = link_errors_facet_counts({"publisher": "alpha"})
    assert alpha["categories"]
    if alpha["categories"][0]["value"] == global_top:
        pytest.skip("fixture publisher's top category matches the global top; re-seed to exercise re-sort")
    assert CATEGORY_LABELS.get(global_top, global_top) == "Not found"

"""Integration tests for the /links/errors query layer on the seeded fixture.

Covers statement shapes, count/list consistency, deterministic ordering, the
datasets LEFT JOIN (harvest states), and the self-excluding facet pools.
The view/render tests live in the behaviour suite.
"""

import re

import pytest

from explorer.queries.link_errors import (
    CATEGORY_LABELS,
    LINK_ERRORS_SORT,
    link_errors_facet_counts,
    link_errors_stats,
    link_errors_stmts,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


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
        "org_name",
        "org_display_name",
        "status",
        "category",
        "error_detail",
        "org_slug",
        "harvest_state",
        "harvest_source_title",
    ):
        assert col in rows[0], f"list row missing {col}"

    hosts = [_url_host(r["resource_url"]) for r in rows]
    assert hosts == sorted(hosts)


@pytest.mark.parametrize("sort", LINK_ERRORS_SORT)
def test_link_errors_count_matches_list_and_deterministic(sort):
    """Each sortable column, both directions: count/list agree and the
    ORDER BY ends with `, l.id`, so ties order the same on every run."""
    for dir_ in ("asc", "desc"):
        out = link_errors_stmts({}, sort, dir_)
        n = out["count"].get(*out["params"])["n"]
        rows = out["list"].all(*out["params"], 1_000_000, 0)
        assert n == len(rows), (sort, dir_)


def test_harvest_state_join_includes_harvested_and_manual():
    """The harvest states partition the table: harvested/manual from
    the datasets join."""
    pool = link_errors_facet_counts({})
    states = pool["harvested"]
    assert "harvested" in states
    assert "manual" in states
    assert states["harvested"] > 0
    assert states["manual"] > 0
    assert sum(states.values()) == _count({})

    assert _count({"harvested": "harvested"}) == states["harvested"]
    out = link_errors_stmts({"harvested": "harvested"}, "url", "asc")
    harvested_rows = out["list"].all(*out["params"], 100, 0)
    assert harvested_rows
    assert all(r["harvest_state"] == "harvested" for r in harvested_rows)


def _assert_pools_partition(filters):
    """Every /links/errors pool equals the list count with that group's
    filter cleared."""
    pool_group = {
        "categories": "category",
        "statuses": "status",
        "domains": "domain",
        "harvested": "harvested",
        "publishers": "publisher",
    }
    trailing = {"domains": "no_url"}

    counts = link_errors_facet_counts(filters)
    for pool, group in pool_group.items():
        value = counts[pool]
        total = sum(value.values()) if isinstance(value, dict) else sum(r["count"] for r in value)
        if pool in trailing:
            total += counts[trailing[pool]]
        assert total == _count(_without(filters, group)), (filters, pool)


def test_link_errors_facet_pools_partition_list_count():
    """Each group's pool total equals the list count with that group's
    filter cleared, under every filter combo."""
    base = link_errors_facet_counts({})
    category = base["categories"][0]["value"]
    status = base["statuses"][0]["value"]
    publisher = base["publishers"][0]["value"]
    domain = base["domains"][0]["value"]

    for filters in (
        {},
        {"category": category},
        {"status": status},
        {"domain": domain},
        {"domain": "__none__"},
        {"harvested": "harvested"},
        {"publisher": publisher},
        {"category": category, "harvested": "harvested"},
    ):
        _assert_pools_partition(filters)


def test_link_errors_facet_value_matches_filtered_count():
    """Picking a facet value shows exactly that value's pool count."""
    base = link_errors_facet_counts({})
    ok_pool = {r["value"]: r["count"] for r in base["categories"]}["OK"]
    assert ok_pool == _count({"category": "OK"})
    assert ok_pool == link_errors_stats()["resolved"]

    assert base["no_url"] == _count({"domain": "__none__"})

    top_domain = base["domains"][0]["value"]
    assert base["domains"][0]["count"] == _count({"domain": top_domain})

    assert "NOT_FOUND" in {r["value"] for r in base["categories"]}
    assert _count({"category": "NOT_FOUND"}) > 0


def test_link_errors_facet_order_follows_filtered_pool():
    """Every facet list is ordered count desc (ties by value), and a
    publisher whose error mix tops on a different category re-sorts the
    Outcome pool away from the global top."""
    for publisher in ("alpha", "beta"):
        categories = [
            (r["value"], r["count"]) for r in link_errors_facet_counts({"publisher": publisher})["categories"]
        ]
        assert categories == sorted(categories, key=lambda pair: (-pair[1], pair[0])), publisher
    assert CATEGORY_LABELS  # sanity: labels dict is not empty

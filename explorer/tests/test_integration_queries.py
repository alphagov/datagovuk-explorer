"""Integration tests for the query layer against the seeded fixture DB.

First slice of the Phase 4 port (docs/test-review-plan.md): the KEEP tests
that were live-DB-shaped, now pointed at the tiny seeded world in the root
conftest.py. Everything here runs with ``django_db`` on the fixture database,
never the live dev snapshot.

Conventions (plan §7): assert invariants (count == list, pools partition the
cleared count, deterministic order), not live content or production counts.
"""

import pytest

from explorer.queries.core import Query
from explorer.queries.datasets import (
    DATASET_TOTAL,
    YEARLY_DATASETS,
    datasets_facet_counts,
    datasets_stmts,
)
from explorer.queries.harvesters import harvest_sources_stmts
from explorer.queries.links import LINKS_STATS, links_facet_counts, links_stmts
from explorer.queries.metadata import METADATA_KEYS, METADATA_VALUES
from explorer.queries.organisations import (
    DATASET_BUCKET_TESTS,
    ORGS,
    organisations_facet_counts,
    organisations_stmts,
)
from explorer.queries.reports import REPORTS, report_facet_counts, report_stmts
from explorer.queries.reviews import get_review, latest_reviews

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# The fixture world itself
# ---------------------------------------------------------------------------
def test_fixture_world_loads():
    """The seed is present: datasets, their 1:1 dataset_json mirror, links,
    link_errors and reviews."""
    assert DATASET_TOTAL.get()["n"] > 0
    assert Query("SELECT COUNT(*) AS n FROM dataset_json").get()["n"] == DATASET_TOTAL.get()["n"]
    assert Query("SELECT COUNT(*) AS n FROM links").get()["n"] > 0
    assert Query("SELECT COUNT(*) AS n FROM link_errors").get()["n"] > 0
    assert latest_reviews(), "fixture reviews should be seeded"


def test_no_arg_statements_execute():
    """Every fixed no-arg statement compiles and runs against the fixture."""
    for stmt in (ORGS, DATASET_TOTAL, YEARLY_DATASETS, LINKS_STATS, METADATA_KEYS):
        assert isinstance(stmt.all(), list)


# ---------------------------------------------------------------------------
# /datasets builder — count/list consistency + the self-exclusion contract
# ---------------------------------------------------------------------------
DATASET_COMBOS = [
    ({}, "organisation", "asc"),
    ({}, "title", "desc"),
    ({"theme": "none"}, "organisation", "asc"),
    ({"source": "harvested"}, "metadata_created", "desc"),
    ({"temporal_year": "pre1900"}, "organisation", "asc"),
    ({"metadata_key": "top:type", "metadata_value": "dataset"}, "title", "desc"),
]


@pytest.mark.parametrize(("filters", "sort", "dir_"), DATASET_COMBOS)
def test_datasets_stmts_count_matches_list(filters, sort, dir_):
    out = datasets_stmts(filters, sort, dir_)
    n = out["count"].get(*out["params"])["n"]
    rows = out["list"].all(*out["params"], 1_000_000, 0)
    assert n == len(rows)
    if rows:
        for col in ("id", "title", "organisation", "metadata_created", "resource_count", "views", "harvested"):
            assert col in rows[0], f"datasets list row missing {col}"


def test_datasets_pagination_and_tiebreak():
    out = datasets_stmts({}, "organisation", "asc")
    page1 = out["list"].all(*out["params"], 100, 0)
    page2 = out["list"].all(*out["params"], 100, 100)
    if len(page1) == 100:
        assert page2
        assert [r["id"] for r in page1] != [r["id"] for r in page2]
    # offset past the end → empty, no error
    assert out["list"].all(*out["params"], 100, 10_000_000) == []


FACET_CONSISTENCY_COMBOS = [
    {},
    {"theme": "none"},
    {"source": "harvested"},
    {"source": "manual"},
    {"links": "0"},
    {"links": "1000+"},
    {"temporal_year": "pre1900"},
    {"temporal_year": "post"},
    {"temporal_year": "none"},
    {"theme": "none", "source": "manual", "temporal_year": "none"},
    {"theme": "Environment", "source": "harvested"},
    {"api": "map-layers"},
]


def _datasets_count(filters):
    out = datasets_stmts(filters, "organisation", "asc")
    return out["count"].get(*out["params"])["n"]


def _without(filters, key):
    return {k: v for k, v in filters.items() if k != key}


@pytest.mark.parametrize("filters", FACET_CONSISTENCY_COMBOS)
def test_facet_pools_total_to_list_count(filters):
    """Each group's pool total equals the page count with that group's
    filter cleared — the core self-exclusion invariant."""
    counts = datasets_facet_counts(filters)

    assert sum(r["count"] for r in counts["themes"]) == _datasets_count(_without(filters, "theme"))

    src = counts["source"]
    assert src["harvested"] + src["manual"] == _datasets_count(_without(filters, "source"))

    assert sum(r["count"] for r in counts["created_years"]) == _datasets_count(_without(filters, "created_year"))

    buckets = counts["temporal_buckets"]
    period_rows = _datasets_count(_without(filters, "temporal_year")) - buckets["none"]
    in_window = sum(r["count"] for r in counts["temporal_years"])
    assert in_window + buckets["pre1900"] + buckets["post"] >= period_rows

    assert sum(r["count"] for r in counts["links"]) == _datasets_count(_without(filters, "links"))


def test_publisher_facet_pools_partition_list_count():
    """The publisher pool partitions the publisher-cleared list count, and
    every row carries a value + display name."""
    base = datasets_facet_counts({})
    publisher = base["publishers"][0]["value"]
    for filters in ({"publisher": publisher}, {"publisher": publisher, "theme": "Environment"}):
        counts = datasets_facet_counts(filters)
        assert sum(r["count"] for r in counts["publishers"]) == _datasets_count(_without(filters, "publisher"))
        assert all(r["value"] and r["name"] for r in counts["publishers"])


def test_publisher_pool_is_ordered_count_desc():
    rows = datasets_facet_counts({})["publishers"]
    assert rows == sorted(rows, key=lambda r: (-r["count"], r["name"].lower()))


def test_theme_none_counts_only_theme_primary_null():
    """`theme=none` counts theme_primary IS NULL. The fixture deliberately
    holds an '' row, which must NOT count as none."""
    none_count = Query("SELECT COUNT(*) AS n FROM datasets WHERE theme_primary IS NULL").get()["n"]
    empty_count = Query("SELECT COUNT(*) AS n FROM datasets WHERE theme_primary = ''").get()["n"]
    assert none_count > 0
    assert empty_count > 0, "fixture must hold an '' theme row to prove the semantics"
    assert _datasets_count({"theme": "none"}) == none_count


def test_theme_facet_has_empty_string_bucket():
    """The theme pool groups '' under its own value (not '__none__')."""
    themes = {r["theme"]: r["count"] for r in datasets_facet_counts({})["themes"]}
    assert "" in themes
    assert "__none__" in themes


# ---------------------------------------------------------------------------
# /organisations facet pools
# ---------------------------------------------------------------------------
def test_org_facet_pools_partition_list_count():
    """Each /organisations pool partitions the list count with that group's
    filter cleared (self-exclusion), using the shared bucket tests as the
    Python reference for the dataset-count buckets."""
    for filters in ({}, {"datasets": "0"}, {"last_published_year": ("__none__",)}):
        counts = organisations_facet_counts(filters)

        created = {r["created_year"]: r["count"] for r in counts["created_years"]}
        no_filter = organisations_stmts(_without(filters, "created_year"), "name", "asc")
        # every org with a real \d{4} created date lands in exactly one year
        assert sum(created.values()) <= no_filter["count"].get(*no_filter["params"])["n"]

        bucket_total = sum(r["count"] for r in counts["datasets"])
        no_bucket = organisations_stmts(_without(filters, "datasets"), "name", "asc")
        assert bucket_total == no_bucket["count"].get(*no_bucket["params"])["n"]


def test_org_dataset_bucket_reference():
    """The SQL dataset bucket matches the Python DATASET_BUCKET_TESTS over
    package_count (the shared bucket boundaries)."""
    rows = {r["slug"]: r for r in ORGS.all()}
    ref = {value: 0 for value, _ in DATASET_BUCKET_TESTS.items()}
    for row in rows.values():
        count = row["package_count"] or 0
        for value, test in DATASET_BUCKET_TESTS.items():
            if test(count):
                ref[value] += 1
                break
    got = {r["bucket"]: r["count"] for r in organisations_facet_counts({})["datasets"]}
    assert got == {k: v for k, v in ref.items() if v}


# ---------------------------------------------------------------------------
# /links + /harvesters builders
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("filters", "sort", "dir_"),
    [
        ({}, "domain", "asc"),
        ({"domain": "__none__"}, "domain", "asc"),
        ({"format": "CSV"}, "dataset_title", "desc"),
        ({"format": "__none__"}, "domain", "asc"),
    ],
)
def test_links_stmts_count_matches_list(filters, sort, dir_):
    out = links_stmts(filters, sort, dir_)
    n = out["count"].get(*out["params"])["n"]
    rows = out["list"].all(*out["params"], 1_000_000, 0)
    assert n == len(rows)
    if rows:
        for col in ("id", "dataset_id", "dataset_title", "name", "url", "host", "format", "org_display_name"):
            assert col in rows[0], f"links list row missing {col}"


def test_links_facet_pools_partition_list_count():
    """Domain + format pools split the cleared list count into non-empty
    values plus their trailing "No URL"/"No format" bucket."""
    for filters in ({}, {"domain": "example.com"}, {"format": "CSV"}):
        pools = links_facet_counts(filters)
        no_domain = links_stmts(_without(filters, "domain"), "domain", "asc")
        total = no_domain["count"].get(*no_domain["params"])["n"]
        assert sum(r["count"] for r in pools["domains"]) + pools["no_url"] == total

        no_format = links_stmts(_without(filters, "format"), "domain", "asc")
        total_fmt = no_format["count"].get(*no_format["params"])["n"]
        assert sum(r["count"] for r in pools["formats"]) + pools["no_format"] == total_fmt


def test_harvest_sources_stmts_consistency():
    for filters in ({}, {"active": "false"}, {"datasets": "0"}):
        for sort, dir_ in (("dataset_count", "desc"), ("title", "asc"), ("last_run", "desc")):
            stmts = harvest_sources_stmts(filters, sort, dir_)
            count = stmts["count"].get(*stmts["params"])["n"]
            rows = stmts["list"].all(*stmts["params"], 1_000_000, 0)
            assert count == len(rows), (filters, sort, dir_)
    stmts = harvest_sources_stmts({}, "dataset_count", "desc")
    row = stmts["list"].all(*stmts["params"], 1, 0)[0]
    for col in ("id", "title", "type", "active", "frequency", "last_run", "org_name", "dataset_count"):
        assert col in row, f"harvester list row missing {col}"


# ---------------------------------------------------------------------------
# Reports — every report's count/list compiles and is deterministic
# ---------------------------------------------------------------------------
def test_every_report_count_matches_list():
    for report in REPORTS:
        out = report_stmts(report)
        n = out["count"].get(*out["params"])["n"]
        rows = out["list"].all(*out["params"], 1_000_000, 0)
        assert n == len(rows), f"report {report['key']}: count {n} != list {len(rows)}"
        assert n >= 0


def test_every_report_deterministic_order():
    for report in REPORTS:
        out = report_stmts(report)
        a = [tuple(r.items()) for r in out["list"].all(*out["params"], 500, 0)]
        b = [tuple(r.items()) for r in out["list"].all(*out["params"], 500, 0)]
        assert a == b, f"report {report['key']} order shuffled between runs"


def test_report_facet_counts_shape():
    """Every faceted report's counts_sql compiles and excludes its own
    filter; each facet key resolves to (sql, params)."""
    for report in REPORTS:
        facets = report.get("facets", [])
        if not facets:
            continue
        stmts = report_facet_counts(report, {})
        assert set(stmts) == {f["key"] for f in facets}, report["key"]
        for sql, params in stmts.values():
            assert isinstance(Query(sql).all(*params), list)


# ---------------------------------------------------------------------------
# Metadata + reviews
# ---------------------------------------------------------------------------
def test_metadata_values_pagination():
    full_key = METADATA_KEYS.all()[0]["key"]
    page1 = METADATA_VALUES.all(full_key, 100, 0)
    assert page1
    assert METADATA_VALUES.all(full_key, 100, 10_000_000) == []


def test_latest_reviews_dedup_semantics():
    rows = latest_reviews()
    assert rows
    ids = [r["dataset_id"] for r in rows]
    assert len(ids) == len(set(ids)), "latest_reviews must dedup to one per dataset"
    assert all(r.get("ok") is True for r in rows), "only ok:true records survive"


def test_get_review_returns_latest_review():
    """The latest ok review for d01 is the later record (overall 5), not the
    earlier one or the ok:false one."""
    rev = get_review("d01")
    assert rev is not None
    assert rev["dataset_id"] == "d01"
    assert rev["overall"] == 5


def test_get_review_missing():
    assert get_review("__no_such_dataset__") is None

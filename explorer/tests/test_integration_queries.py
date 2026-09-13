"""Integration tests for the query layer against the seeded fixture DB.

Phase 4 port (docs/test-review-plan.md) of the KEEP/REWRITE items in the
legacy ``test_queries.py``: statement shapes, count/list consistency,
deterministic ordering, self-excluding facet pools, and review dedup — all
against the tiny seed in the root ``conftest.py``, never the live snapshot.

Conventions (plan §7): assert invariants (count == list, pools partition the
cleared count, deterministic order), not live content or production counts.
"""

import pytest

from explorer.buckets import bucket_tests
from explorer.queries.core import Query
from explorer.queries.datasets import (
    DATASET_COUNT,
    DATASET_TOTAL,
    FETCHED_SLUGS,
    THEME_COUNTS,
    YEARLY_DATASETS,
    datasets_facet_counts,
    datasets_stmts,
    org_datasets_stmts,
    source_datasets_stmts,
)
from explorer.queries.harvesters import HARVEST_SOURCES, harvest_sources_stmts
from explorer.queries.links import (
    LINKS_STATS,
    links_facet_counts,
    links_stmts,
)
from explorer.queries.metadata import METADATA_KEYS, METADATA_VALUE_COUNT, METADATA_VALUES
from explorer.queries.organisations import (
    DATASET_BUCKET_TESTS,
    LAST_PUBLISHED_BY_ORG,
    ORG,
    ORGS,
    RESOURCE_COUNTS,
    VIEWS_BY_ORG,
    organisations_facet_counts,
    organisations_stmts,
)
from explorer.queries.reviews import get_classification, get_review, latest_reviews
from explorer.queries.series import SERIES_COUNT, series_list_stmt
from explorer.views.core import PAGE_SIZE

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _without(filters, key):
    return {k: v for k, v in filters.items() if k != key}


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
    for stmt in (
        ORGS,
        RESOURCE_COUNTS,
        VIEWS_BY_ORG,
        LAST_PUBLISHED_BY_ORG,
        FETCHED_SLUGS,
        DATASET_TOTAL,
        YEARLY_DATASETS,
        THEME_COUNTS,
        LINKS_STATS,
        METADATA_KEYS,
        SERIES_COUNT,
    ):
        assert isinstance(stmt.all(), list)


def test_orgs_row_shape():
    rows = ORGS.all()
    assert rows
    for col in (
        "slug",
        "name",
        "display_name",
        "package_count",
        "type",
        "state",
        "approval_status",
        "created",
        "title",
    ):
        assert col in rows[0], f"orgs row missing {col}"


def test_dataset_total():
    """datasets ↔ dataset_json is a real pipeline 1:1 invariant."""
    total = DATASET_TOTAL.get()
    assert total is not None
    assert total["n"] > 0
    assert Query("SELECT COUNT(*) AS n FROM dataset_json").get()["n"] == total["n"]


def test_stats_shapes():
    """The /links and /series header stats expose their documented keys."""
    links = LINKS_STATS.get()
    assert links is not None
    assert "total" in links
    assert links["total"] > 0
    series = SERIES_COUNT.get()
    assert series is not None
    assert "n" in series


# ---------------------------------------------------------------------------
# Per-org / per-source builders
# ---------------------------------------------------------------------------
def test_org_statements_consistency():
    """The org page builder: count == page-list total, and the row shape
    the template reads."""
    org = next(o for o in ORGS.all() if (DATASET_COUNT.get(o["slug"]) or {}).get("count", 0) > 0)
    slug = org["slug"]
    count = (DATASET_COUNT.get(slug) or {}).get("count", 0)
    stmts = org_datasets_stmts(slug, "metadata_modified", "desc")
    assert stmts["count"].get(*stmts["params"])["n"] == count
    assert count > 0

    rows = []
    offset = 0
    while True:
        page = stmts["list"].all(*stmts["params"], PAGE_SIZE, offset)
        if not page:
            break
        rows.extend(page)
        offset += PAGE_SIZE
        assert len(page) <= PAGE_SIZE
    assert len(rows) == count
    for col in ("id", "title", "name", "metadata_created", "metadata_modified", "resource_count", "harvested", "views"):
        assert col in rows[0], f"org builder row missing {col}"


def test_source_statements_consistency():
    """The harvest-source page builder: count == page-list total, and the
    row shape the template reads."""
    with_datasets = [r for r in HARVEST_SOURCES.all() if r["dataset_count"] > 0]
    assert with_datasets
    source_id = with_datasets[0]["id"]
    stmts = source_datasets_stmts(source_id, "metadata_modified", "desc")
    count = stmts["count"].get(*stmts["params"])["n"]
    assert count > 0
    rows = stmts["list"].all(*stmts["params"], PAGE_SIZE, 0)
    assert len(rows) == count
    for col in ("id", "org_slug", "title", "name", "metadata_created", "metadata_modified", "resource_count", "views"):
        assert col in rows[0], f"source builder row missing {col}"


def test_org_detail_row():
    """org(slug) resolves the same org the orgs list names."""
    slug = ORGS.all()[0]["slug"]
    row = ORG.get(slug)
    assert row is not None
    assert row["slug"] == slug


def test_organisations_stmts_consistency():
    """/organisations list builder: count == page-list total across every
    filter/sort combo, the row shape, and deterministic pages."""
    combos = [
        {},
        {"datasets": "0"},
        {"datasets": "1-10"},
        {"last_published_year": ("__none__",)},
        {"created_year": "2010"},
    ]
    for filters in combos:
        for sort, dir_ in (("name", "asc"), ("dataset_count", "desc"), ("last_published", "desc")):
            stmts = organisations_stmts(filters, sort, dir_)
            count = stmts["count"].get(*stmts["params"])["n"]
            rows = stmts["list"].all(*stmts["params"], 1_000_000, 0)
            assert count == len(rows), (filters, sort, dir_)

    stmts = organisations_stmts({}, "name", "asc")
    row = stmts["list"].all(*stmts["params"], 1, 0)[0]
    for col in (
        "slug",
        "display_name",
        "package_count",
        "type",
        "state",
        "approval_status",
        "created",
        "total_resources",
        "total_views",
        "last_published",
        "has_data",
    ):
        assert col in row, f"organisation list row missing {col}"
    a = [tuple(r.items()) for r in stmts["list"].all(*stmts["params"], PAGE_SIZE, 0)]
    b = [tuple(r.items()) for r in stmts["list"].all(*stmts["params"], PAGE_SIZE, 0)]
    assert a == b


def test_harvest_sources_stmts_consistency():
    """/harvesters list builder: count == page-list total, row shape and
    deterministic pages."""
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
# /datasets builder + self-excluding facet pools
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
    assert out["list"].all(*out["params"], 100, 10_000_000) == []
    a = [r["id"] for r in out["list"].all(*out["params"], 500, 0)]
    b = [r["id"] for r in out["list"].all(*out["params"], 500, 0)]
    assert a == b


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
    {"created_year": "2024", "theme": "Environment", "temporal_year": "none"},
    {"api": "map-layers"},
]


def _datasets_count(filters):
    out = datasets_stmts(filters, "organisation", "asc")
    return out["count"].get(*out["params"])["n"]


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


def test_links_facet_pool_matches_python_reference():
    """The links pool equals the shared bucket tests applied to
    COALESCE(resource_count, 0), for no filter and under other facets
    (self-exclusion: the links group's own filter never narrows its pool)."""
    rows = Query("SELECT COALESCE(resource_count, 0) AS rc, harvested, theme_primary FROM datasets").all()
    tests = bucket_tests()

    def kept(row, filters):
        return not (filters.get("source") == "harvested" and row["harvested"] != 1) and not (
            filters.get("theme") == "none" and row["theme_primary"] is not None
        )

    for filters in ({}, {"source": "harvested"}, {"theme": "none"}):
        counts = datasets_facet_counts(filters)
        pool = dict.fromkeys(tests, 0)
        for row in rows:
            if not kept(row, filters):
                continue
            for value, test in tests.items():
                if test(row["rc"]):
                    pool[value] += 1
                    break
        got = {r["bucket"]: r["count"] for r in counts["links"]}
        assert got == {k: v for k, v in pool.items() if v}, filters


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
def _org_count(filters):
    stmt = organisations_stmts(filters, "name", "asc")
    return stmt["count"].get(*stmt["params"])["n"]


def test_org_facet_pools_partition_list_count():
    """Each /organisations pool partitions the list count with that group's
    filter cleared — the same self-exclusion contract as /datasets."""
    for filters in (
        {},
        {"datasets": "0"},
        {"created_year": "2010"},
        {"last_published_year": ("2024",)},
        {"last_published_year": ("__none__",)},
    ):
        counts = organisations_facet_counts(filters)

        years = sum(r["count"] for r in counts["created_years"])
        assert years == _org_count(_without(filters, "created_year")), filters

        published = sum(r["count"] for r in counts["last_published_years"]) + counts["no_last_published_year"]
        assert published == _org_count(_without(filters, "last_published_year")), filters

        buckets = sum(r["count"] for r in counts["datasets"])
        assert buckets == _org_count(_without(filters, "datasets")), filters


def test_org_dataset_bucket_reference():
    """The SQL dataset bucket matches the Python DATASET_BUCKET_TESTS over
    package_count (the shared bucket boundaries)."""
    ref = {value: 0 for value, _ in DATASET_BUCKET_TESTS.items()}
    for row in ORGS.all():
        count = row["package_count"] or 0
        for value, test in DATASET_BUCKET_TESTS.items():
            if test(count):
                ref[value] += 1
                break
    got = {r["bucket"]: r["count"] for r in organisations_facet_counts({})["datasets"]}
    assert got == {k: v for k, v in ref.items() if v}


# ---------------------------------------------------------------------------
# /links builder + facet pools
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
        assert (
            sum(r["count"] for r in pools["domains"]) + pools["no_url"]
            == no_domain["count"].get(
                *no_domain["params"],
            )["n"]
        )
        no_format = links_stmts(_without(filters, "format"), "domain", "asc")
        assert (
            sum(r["count"] for r in pools["formats"]) + pools["no_format"]
            == no_format["count"].get(
                *no_format["params"],
            )["n"]
        )


# ---------------------------------------------------------------------------
# Series, metadata, reviews
# ---------------------------------------------------------------------------
def test_series_list_stmt():
    for sort, dir_ in [("dataset_count", "desc"), ("root_title", "asc"), ("org_count", "desc"), ("type", "asc")]:
        rows = series_list_stmt(sort, dir_).all(50, 0)
        assert len(rows) <= 50
        if rows:
            for col in ("id", "root_title", "dataset_count", "org_count", "type"):
                assert col in rows[0], f"series row missing {col}"


def test_metadata_values_pagination():
    full_key = METADATA_KEYS.all()[0]["key"]
    total = METADATA_VALUE_COUNT.get(full_key)["n"]
    page1 = METADATA_VALUES.all(full_key, 100, 0)
    assert len(page1) == min(100, total)
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
    assert rev == next(r for r in latest_reviews() if r["dataset_id"] == "d01")


def test_get_classification_is_get_review():
    assert get_classification is get_review


def test_get_review_missing():
    assert get_review("__no_such_dataset__") is None

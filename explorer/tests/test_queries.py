"""Query-layer shape + consistency tests against the live DB.

Locks in the query layer: statement shapes, count/list consistency,
deterministic ordering, and the reviews helpers' dedup semantics.

App tests read the *live* dev DB read-only (see tests/conftest.py) — they
skip when the DB is unreachable or empty. Expected row shapes are asserted
as key-superset checks so schema additions don't break the suite, but a
missing column the views rely on still fails.
"""

import re

import pytest

from explorer.queries.core import Query, facet_where
from explorer.queries.datasets import (
    DATASET_COUNT,
    DATASET_TOTAL,
    FETCHED_SLUGS,
    THEME_COUNTS,
    YEARLY_DATASETS,
    dataset_created_years,
    datasets_facet_counts,
    datasets_stmts,
    org_datasets_stmts,
    source_datasets_stmts,
)
from explorer.queries.harvesters import HARVEST_SOURCES, harvest_sources_stmts
from explorer.queries.links import (
    _LINKS_CLAUSES,
    LINKS_STATS,
    links_facet_counts,
    links_stmts,
)
from explorer.queries.metadata import (
    METADATA_KEYS,
    METADATA_VALUE_COUNT,
    METADATA_VALUES,
)
from explorer.queries.organisations import (
    DATASET_BUCKET_TESTS,
    DATASET_BUCKETS,
    LAST_PUBLISHED_BY_ORG,
    ORG,
    ORG_AGGREGATES,
    ORGS,
    RESOURCE_COUNTS,
    VIEWS_BY_ORG,
    org_created_years,
    organisations_facet_counts,
    organisations_stmts,
)
from explorer.queries.reports import (
    REPORTS,
    report_facet_counts,
    report_stmts,
)
from explorer.queries.reviews import get_classification, get_review, latest_reviews
from explorer.queries.series import SERIES_COUNT, series_list_stmt
from explorer.views.core import PAGE_SIZE

pytestmark = pytest.mark.usefixtures("db_ready")


# ---------------------------------------------------------------------------
# Fixed statements
# ---------------------------------------------------------------------------
def test_no_arg_statements_execute():
    """Every no-arg statement executes against the live DB."""
    # The fixed no-arg statements — the ones the views build every page
    # from. (Param-taking statements are covered by the per-domain tests
    # below.)
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
        rows = stmt.all()
        assert isinstance(rows, list), f"{stmt}.all() returned {type(rows)}"


def test_orgs_row_shape():
    rows = ORGS.all()
    assert len(rows) > 0
    row = rows[0]
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
        assert col in row, f"orgs row missing {col}"


def test_dataset_total():
    total_row = DATASET_TOTAL.get()
    assert total_row is not None
    n = total_row["n"]
    assert n > 0
    # Count consistency: the dataset_json table mirrors datasets 1:1
    json_rows = Query("SELECT COUNT(*) AS n FROM dataset_json").get()
    assert json_rows is not None
    assert json_rows["n"] == n


def test_links_stats_shape():
    row = LINKS_STATS.get()
    assert row is not None
    assert "total" in row
    assert row["total"] > 0


def test_series_count_shape():
    row = SERIES_COUNT.get()
    assert row is not None
    assert "n" in row


# ---------------------------------------------------------------------------
# Per-org statements
# ---------------------------------------------------------------------------
def test_org_statements_consistency():
    """The org page's builder: count == page-list total across every page,
    and the row shape the template reads."""
    org = next(o for o in ORGS.all() if (DATASET_COUNT.get(o["slug"]) or {}).get("count", 0) > 0)
    slug = org["slug"]
    count = (DATASET_COUNT.get(slug) or {}).get("count", 0)
    stmts = org_datasets_stmts(slug, "metadata_modified", "desc")
    assert stmts["count"].get(*stmts["params"])["n"] == count
    assert count > 0

    # Walk every page at PAGE_SIZE — the pages must add up to the count
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

    row = rows[0]
    for col in (
        "id",
        "title",
        "name",
        "metadata_created",
        "metadata_modified",
        "resource_count",
        "harvested",
        "views",
    ):
        assert col in row, f"org builder row missing {col}"


def test_source_statements_consistency():
    """The harvest-source page's builder: count == page-list total across
    every page, and the row shape the template reads."""
    with_datasets = [r for r in HARVEST_SOURCES.all() if r["dataset_count"] > 0]
    assert with_datasets
    source_id = with_datasets[0]["id"]
    stmts = source_datasets_stmts(source_id, "metadata_modified", "desc")
    count = stmts["count"].get(*stmts["params"])["n"]
    assert count > 0

    # Walk every page at PAGE_SIZE — the pages must add up to the count
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

    row = rows[0]
    for col in (
        "id",
        "org_slug",
        "title",
        "name",
        "metadata_created",
        "metadata_modified",
        "resource_count",
        "views",
    ):
        assert col in row, f"source builder row missing {col}"


def test_org_detail_row():
    """org(slug) resolves the same org the orgs list names."""
    slug = ORGS.all()[0]["slug"]
    row = ORG.get(slug)
    assert row is not None
    assert row["slug"] == slug


# ---------------------------------------------------------------------------
# /datasets builder — count/list consistency + pagination
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
    assert len(rows) == 0 or n == len(rows)  # (identical check, for clarity)
    # list rows carry the columns the /datasets template renders
    if rows:
        for col in (
            "id",
            "title",
            "organisation",
            "metadata_created",
            "resource_count",
            "views",
            "harvested",
        ):
            assert col in rows[0], f"datasets list row missing {col}"


def test_datasets_stmts_pagination():
    out = datasets_stmts({}, "organisation", "asc")
    n = out["count"].get(*out["params"])["n"]
    page1 = out["list"].all(*out["params"], 100, 0)
    page2 = out["list"].all(*out["params"], 100, 100)
    if n > 100:
        assert page1
        assert page2
        assert [r["id"] for r in page1] != [r["id"] for r in page2]
    # offset past the end → empty, no error
    assert out["list"].all(*out["params"], 100, 10_000_000) == []


def test_datasets_tiebreak_deterministic():
    """Two runs give the same order — when sort values tie, order by d.id."""
    out = datasets_stmts({}, "organisation", "asc")
    a = [r["id"] for r in out["list"].all(*out["params"], 500, 0)]
    b = [r["id"] for r in out["list"].all(*out["params"], 500, 0)]
    assert a == b


# ---------------------------------------------------------------------------
# /datasets sidebar facet counts (SQL aggregates) — pool-vs-list consistency
# ---------------------------------------------------------------------------
# Each group counts over the pool filtered by every *other* group, so the
# pool total equals the page count with that group's filter cleared.
FACET_CONSISTENCY_COMBOS = [
    {},
    {"theme": "none"},
    {"source": "harvested"},
    {"source": "manual"},
    {"links": "0"},
    {"links": "1-10"},
    {"links": "1000+"},
    {"temporal_year": "pre1900"},
    {"temporal_year": "post"},
    {"temporal_year": "none"},
    {"theme": "none", "source": "manual", "temporal_year": "post"},
    {"theme": "none", "source": "harvested", "links": "0"},
]


def _datasets_count(filters):
    out = datasets_stmts(filters, "organisation", "asc")
    return out["count"].get(*out["params"])["n"]


def _without(filters, key):
    return {k: v for k, v in filters.items() if k != key}


@pytest.mark.parametrize("filters", FACET_CONSISTENCY_COMBOS)
def test_facet_pools_total_to_list_count(filters):
    """Each group's pool total equals the page count with that group's
    filter cleared (contract items 1-2)."""
    counts = datasets_facet_counts(filters)

    # theme: every pool row lands in exactly one bucket (__none__ for NULL)
    assert sum(r["count"] for r in counts["themes"]) == _datasets_count(
        _without(filters, "theme"),
    )

    # source: harvested + manual (harvested is 0/1, no NULLs)
    src = counts["source"]
    assert src["harvested"] + src["manual"] == _datasets_count(
        _without(filters, "source"),
    )

    # created years: every dataset has metadata_created (no NULLs), so the
    # per-year counts sum to the full pool
    assert sum(r["count"] for r in counts["created_years"]) == _datasets_count(
        _without(filters, "created_year"),
    )

    # temporal: rows with no periods feed the `none` bucket; every row WITH
    # periods hits at least one of pre1900 / post / an in-window year. A row
    # can hit several (coverage spanning the window edges), so the bucket
    # sum is a lower bound on nothing in particular — the invariant is that
    # it covers every period row at least once.
    buckets = counts["temporal_buckets"]
    period_rows = _datasets_count(_without(filters, "temporal_year")) - buckets["none"]
    in_window = sum(r["count"] for r in counts["temporal_years"])
    assert in_window + buckets["pre1900"] + buckets["post"] >= period_rows

    # links: every dataset lands in exactly one bucket (NULL resource_count
    # COALESCEs into the 0 bucket), so the pool total equals the page count
    # with the links filter cleared.
    assert sum(r["count"] for r in counts["links"]) == _datasets_count(
        _without(filters, "links"),
    )


def test_publisher_facet_pools_partition_list_count():
    """The publisher pool partitions the publisher-cleared list count —
    every dataset carries an org slug, so the org rows always sum to the
    whole pool, whether alone or under another active facet (the live-data
    analogue of the static combos above, whose publisher value can't be
    hardcoded)."""
    base = datasets_facet_counts({})
    publisher = base["publishers"][0]["value"]
    theme = next(t["theme"] for t in THEME_COUNTS.all() if t["theme"] != "__none__")

    for filters in (
        {"publisher": publisher},
        {"publisher": publisher, "theme": theme},
        {"publisher": publisher, "source": "manual"},
        {"publisher": publisher, "temporal_year": "post"},
    ):
        counts = datasets_facet_counts(filters)
        assert sum(r["count"] for r in counts["publishers"]) == _datasets_count(
            _without(filters, "publisher"),
        ), filters
        # every row names its org (value = slug, name = display name)
        assert all(r["value"] and r["name"] for r in counts["publishers"])

    # the picked publisher survives into its own sibling-filtered pool
    counts = datasets_facet_counts({"publisher": publisher, "theme": theme})
    assert any(r["value"] == publisher for r in counts["publishers"])
    assert sum(r["count"] for r in datasets_facet_counts({"theme": theme})["publishers"]) == _datasets_count(
        {"theme": theme},
    )


def test_publisher_pool_is_ordered_count_desc():
    """The pool comes back count desc, name asc — the sidebar's render
    order (biggest publishers first, ties alphabetical by display name)."""
    rows = datasets_facet_counts({})["publishers"]
    assert rows == sorted(rows, key=lambda r: (-r["count"], r["name"].lower()))


def test_facet_counts_with_live_year_and_theme():
    """Same consistency check with a real created year + theme from the
    live data."""
    year = YEARLY_DATASETS.all()[0]["year"]
    theme = next(t["theme"] for t in THEME_COUNTS.all() if t["theme"] != "__none__")
    filters = {"created_year": year, "theme": theme, "temporal_year": "none"}
    counts = datasets_facet_counts(filters)
    assert sum(r["count"] for r in counts["themes"]) == _datasets_count(
        _without(filters, "theme"),
    )
    assert sum(r["count"] for r in counts["created_years"]) == _datasets_count(
        _without(filters, "created_year"),
    )
    buckets = counts["temporal_buckets"]
    period_rows = _datasets_count(_without(filters, "temporal_year")) - buckets["none"]
    assert sum(r["count"] for r in counts["temporal_years"]) + buckets["pre1900"] + buckets["post"] >= period_rows


def test_links_facet_pool_matches_python_reference():
    """The links pool equals the Python reference buckets over the same
    datasets — the shared bucket tests applied to COALESCE(resource_count,
    0) — for no filter and under another active facet (self-exclusion: the
    links group's own filter never narrows its pool). Locks in the 0 /
    open-ended-top bucket boundaries and the COALESCE-into-0 fallback, the
    same way the orgs bucket reference does for package_count."""
    from explorer.buckets import bucket_tests  # noqa: PLC0415

    rows = Query(
        "SELECT COALESCE(resource_count, 0) AS rc, harvested, theme_primary FROM datasets",
    ).all()
    tests = bucket_tests()

    def kept(row, filters):
        """Reference `every other facet` match — the filters the SQL pool
        applies when the links group is excluded."""
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
    """Contract item 3: `theme=none` counts theme_primary IS NULL — the SQL
    semantics (an '' theme would NOT count as none). No '' rows exist, so
    the assertion checks the SQL semantics, not the data."""
    none_count = Query(
        "SELECT COUNT(*) AS n FROM datasets WHERE theme_primary IS NULL",
    ).get()
    assert none_count is not None
    assert _datasets_count({"theme": "none"}) == none_count["n"]

    empty_count = Query(
        "SELECT COUNT(*) AS n FROM datasets WHERE theme_primary = ''",
    ).get()
    assert empty_count is not None
    assert empty_count["n"] == 0


# ---------------------------------------------------------------------------
# /organisations sidebar facet counts (SQL self-excluding aggregates)
# ---------------------------------------------------------------------------
# Each group counts over the pool filtered by the *other* two groups (the
# same self-exclusion contract as /datasets). The reference pools below
# are computed in Python over the merged org rows — the semantics the SQL
# GROUP BYs must match exactly.


def _org_rows():
    from explorer.views.organisations import _merge_org_rows  # noqa: PLC0415

    return _merge_org_rows(ORGS.all(), ORG_AGGREGATES.all())


def _pub_year_match(o, pub_years):
    """Reference last-published-year match — the rule the SQL
    last_published_year clause mirrors, kept here so the Python reference
    sits next to its tests: __none__ matches orgs with no last-published
    year, a real year list matches those years."""
    if "__none__" in pub_years:
        return o["last_published_year"] is None
    return o["last_published_year"] in pub_years


def _org_ref_pools(filters):
    r"""(created_years, last_published_years, no_last_published_year,
    datasets) reference pools — each group counts the rows matching every
    filter except its own, counted exactly as the Python reference does
    (dataset_count = package_count or 0, the \d{4} created guard, the
    `if y` last-published skip). The last-published pool splits into the
    year list + the never-published (no last-published) bucket."""

    def kept(exclude):
        return [
            o
            for o in _org_rows()
            if (
                filters.get("created_year") is None
                or exclude == "created_year"
                or o["created_year"] == filters["created_year"]
            )
            and (
                not filters.get("last_published_year")
                or exclude == "last_published_year"
                or _pub_year_match(o, filters["last_published_year"])
            )
            and (
                filters.get("datasets") is None
                or exclude == "datasets"
                or DATASET_BUCKET_TESTS[filters["datasets"]](o["dataset_count"])
            )
        ]

    year_pool: dict[str, int] = {}
    for o in kept("created_year"):
        y = o["created_year"]
        if re.fullmatch(r"\d{4}", y):
            year_pool[y] = year_pool.get(y, 0) + 1

    pub_pool: dict[str, int] = {}
    no_pub_pool = 0
    for o in kept("last_published_year"):
        y = o["last_published_year"]
        if y:
            pub_pool[y] = pub_pool.get(y, 0) + 1
        else:
            no_pub_pool += 1

    bucket_pool = {value: 0 for value, _ in DATASET_BUCKETS}
    for o in kept("datasets"):
        for value, _ in DATASET_BUCKETS:
            if DATASET_BUCKET_TESTS[value](o["dataset_count"]):
                bucket_pool[value] += 1
                break
    return year_pool, pub_pool, no_pub_pool, {k: v for k, v in bucket_pool.items() if v}


def _org_facet_combos():
    """Filter combos built from the live data — real years/buckets, so the
    pools aren't vacuously empty."""
    rows = _org_rows()
    years = sorted({y for o in rows if (y := o["created_year"])}, reverse=True)
    pub_years = sorted(
        {o["last_published_year"] for o in rows if o["last_published_year"]},
        reverse=True,
    )
    combos: list[dict[str, str | tuple[str, ...]]] = [
        {},
        {"datasets": "0"},
        {"datasets": "1000+"},
    ]
    if years:
        combos.append({"created_year": years[0]})
    if pub_years:
        combos.append({"last_published_year": (pub_years[0],)})
    combos.append({"last_published_year": ("__none__",)})
    if len(pub_years) > 1:
        combos.append({"last_published_year": tuple(pub_years[:2])})
    if len(years) > 1 and len(pub_years) > 1:
        combos.append(
            {"created_year": years[-1], "last_published_year": tuple(pub_years[:2]), "datasets": "1-10"},
        )
    return combos


def test_org_facet_pools_match_python_reference():
    """The SQL pools equal the Python reference pools for the same filters
    — the bucket-boundary (0 / open-ended top) and guard semantics, with
    self-exclusion per group. Combos are built from live data (inside the
    test, after the db_ready fixture unblocks the DB) so the pools aren't
    vacuously empty."""
    for filters in _org_facet_combos():
        counts = organisations_facet_counts(filters)
        year_ref, pub_ref, no_pub_ref, bucket_ref = _org_ref_pools(filters)
        assert {r["created_year"]: r["count"] for r in counts["created_years"]} == year_ref, filters
        assert {
            r["last_published_year"]: r["count"] for r in counts["last_published_years"]
        } == pub_ref, filters
        assert counts["no_last_published_year"] == no_pub_ref, filters
        assert {r["bucket"]: r["count"] for r in counts["datasets"]} == bucket_ref, filters


def test_org_facet_counts_with_live_year_and_pubyear():
    """Same consistency check with a real created year + last-published
    year + bucket from the live data — the multi-facet self-exclusion case
    (mirrors the /datasets live-year-and-theme test)."""
    rows = _org_rows()
    year = next((o["created_year"] for o in rows if o["created_year"]), None)
    pub_year = next((o["last_published_year"] for o in rows if o["last_published_year"]), None)
    if not year or not pub_year:
        pytest.skip("no valid year/pubyear in live data")
    filters = {"created_year": year, "last_published_year": (pub_year,), "datasets": "1-10"}
    counts = organisations_facet_counts(filters)
    year_ref, pub_ref, no_pub_ref, bucket_ref = _org_ref_pools(filters)
    assert {r["created_year"]: r["count"] for r in counts["created_years"]} == year_ref
    assert {
        r["last_published_year"]: r["count"] for r in counts["last_published_years"]
    } == pub_ref
    assert counts["no_last_published_year"] == no_pub_ref
    assert {r["bucket"]: r["count"] for r in counts["datasets"]} == bucket_ref


def test_harvest_sources_stmts_consistency():
    """/harvesters list builder: count == page-list total across every
    filter/sort combo, the row shape the template reads, and
    deterministic pages (when sort values tie, order by
    `LOWER(h.title), h.id`)."""
    from collections import Counter  # noqa: PLC0415

    from explorer.queries.harvesters import harvest_source_rows  # noqa: PLC0415

    rows = harvest_source_rows()
    type_counts = Counter(r["type"] for r in rows)
    top_type = type_counts.most_common(1)[0][0] if type_counts else None

    combos = [
        {},
        {"active": "false"},
        {"datasets": "0"},
        {"datasets": "1000+"},
    ]
    if top_type:
        combos.append({"type": top_type})

    for filters in combos:
        for sort, dir_ in (("dataset_count", "desc"), ("title", "asc"), ("last_run", "desc")):
            stmts = harvest_sources_stmts(filters, sort, dir_)
            count = stmts["count"].get(*stmts["params"])["n"]
            rows_all = stmts["list"].all(*stmts["params"], 1_000_000, 0)
            assert count == len(rows_all), (filters, sort, dir_)

    # Row shape the template reads
    stmts = harvest_sources_stmts({}, "dataset_count", "desc")
    row = stmts["list"].all(*stmts["params"], 1, 0)[0]
    for col in ("id", "title", "type", "active", "frequency", "last_run", "org_name", "dataset_count"):
        assert col in row, f"harvester list row missing {col}"

    # Deterministic order — two runs give identical pages
    a = [tuple(r.items()) for r in stmts["list"].all(*stmts["params"], PAGE_SIZE, 0)]
    b = [tuple(r.items()) for r in stmts["list"].all(*stmts["params"], PAGE_SIZE, 0)]
    assert a == b


def test_organisations_stmts_consistency():
    """/organisations list builder: count == page-list total across every
    filter/sort combo, the row shape the template reads, and deterministic
    pages (when sort values tie, order by `LOWER(o.display_name), o.slug`)."""
    from collections import Counter  # noqa: PLC0415

    rows = _org_rows()
    year_counts = Counter(o["created_year"] for o in rows if o["created_year"])
    top_year = year_counts.most_common(1)[0][0] if year_counts else None

    combos = [
        {},
        {"datasets": "0"},
        {"datasets": "1000+"},
        {"last_published_year": ("__none__",)},
    ]
    if top_year:
        combos.append({"created_year": top_year})

    for filters in combos:
        for sort, dir_ in (("name", "asc"), ("dataset_count", "desc"), ("last_published", "desc")):
            stmts = organisations_stmts(filters, sort, dir_)
            count = stmts["count"].get(*stmts["params"])["n"]
            rows_all = stmts["list"].all(*stmts["params"], 1_000_000, 0)
            assert count == len(rows_all), (filters, sort, dir_)

    # Row shape the template reads
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

    # Deterministic order — two runs give identical pages
    a = [tuple(r.items()) for r in stmts["list"].all(*stmts["params"], PAGE_SIZE, 0)]
    b = [tuple(r.items()) for r in stmts["list"].all(*stmts["params"], PAGE_SIZE, 0)]
    assert a == b


# ---------------------------------------------------------------------------
# /links builder
# ---------------------------------------------------------------------------
LINK_COMBOS = [
    ({}, "domain", "asc"),
    ({"domain": "__none__"}, "domain", "asc"),
    ({"format": "CSV"}, "dataset_title", "desc"),
    ({"format": "__none__"}, "domain", "asc"),
]


@pytest.mark.parametrize(("filters", "sort", "dir_"), LINK_COMBOS)
def test_links_stmts_count_matches_list(filters, sort, dir_):
    out = links_stmts(filters, sort, dir_)
    n = out["count"].get(*out["params"])["n"]
    rows = out["list"].all(*out["params"], 1_000_000, 0)
    assert n == len(rows)
    if rows:
        for col in (
            "id",
            "dataset_id",
            "dataset_title",
            "name",
            "url",
            "host",
            "format",
            "org_display_name",
        ):
            assert col in rows[0], f"links list row missing {col}"


# ---------------------------------------------------------------------------
# /links sidebar facet counts (SQL self-excluding aggregates)
# ---------------------------------------------------------------------------
# Each group counts over the pool filtered by the *other* groups (the
# /datasets self-exclusion contract). The pools deliberately exclude
# NULL/'' values — so the pool total equals the list count with that
# group's filter cleared, minus the excluded rows. The domain and format
# groups each split their pool into two halves (all domains + the "No URL"
# trailing bucket; all formats + the "No format" trailing bucket) that
# partition it.


def _assert_links_pool_consistency(filters):
    counts = links_facet_counts(filters)
    pool_keys = {"domain": "domains", "format": "formats", "created_year": "created_years"}
    for group in ("domain", "format", "created_year"):
        total = _links_count(_without(filters, group))
        frag, params = facet_where(_LINKS_CLAUSES, filters, exclude=group)
        if group == "domain":
            domains_total = sum(r["count"] for r in counts["domains"])
            no_value = counts["no_url"]
            non_null_where = f"{frag} AND l.host IS NOT NULL" if frag else " WHERE l.host IS NOT NULL"
            non_null = Query(f"SELECT COUNT(*) AS n FROM links l{non_null_where}").get(*params)["n"]
            assert no_value + non_null == total, (filters, group)
            # the domains pool is uncapped — it covers every non-NULL host
            assert domains_total == non_null, (filters, group)
        else:
            pool = sum(r["count"] for r in counts[pool_keys[group]])
            col = "format_norm" if group == "format" else "year_created"
            null_where = (
                f"{frag} AND ({col} IS NULL OR {col} = '')" if frag else f" WHERE ({col} IS NULL OR {col} = '')"
            )
            null_count = Query(f"SELECT COUNT(*) AS n FROM links l{null_where}").get(*params)["n"]
            if group == "format":
                # the No format trailing bucket is the same pool as the
                # inline null-count above
                assert counts["no_format"] == null_count, (filters, group)
            assert pool + null_count == total, (filters, group)


def _links_count(filters):
    out = links_stmts(filters, "domain", "asc")
    return out["count"].get(*out["params"])["n"]


def test_links_facet_pools_total_to_list_count():
    """Each group's pool total equals the list count with that group's
    filter cleared, minus the rows the pool deliberately excludes — the
    NULL/'' values, and (domain) the no-URL bucket (the domains pool
    itself is uncapped). Combos use real domains/formats/years from the
    live pools."""
    base = links_facet_counts({})
    domain = base["domains"][0]["domain"]
    fmt = base["formats"][0]["fmt"]
    year = base["created_years"][0]["created_year"]
    for filters in (
        {},
        {"domain": "__none__"},
        {"format": "__none__"},
        {"domain": domain},
        {"format": fmt},
        {"created_year": year},
        {"domain": domain, "format": fmt, "created_year": year},
    ):
        _assert_links_pool_consistency(filters)


def test_links_facet_counts_with_live_filters():
    """Same consistency check with a real domain+format+year combo — the
    multi-facet self-exclusion case (mirrors the /datasets live-year-and-
    theme test): sibling pools shrink under the other active filters."""
    base = links_facet_counts({})
    domain = base["domains"][0]["domain"]
    fmt = base["formats"][0]["fmt"]
    year = base["created_years"][0]["created_year"]
    filters = {"domain": domain, "format": fmt, "created_year": year}
    _assert_links_pool_consistency(filters)
    counts = links_facet_counts(filters)

    def pool_total(p, group):
        pool_keys = {"domain": "domains", "format": "formats", "created_year": "created_years"}
        if group == "domain":
            return sum(r["count"] for r in p["domains"]) + p["no_url"]
        if group == "format":
            return sum(r["count"] for r in p["formats"]) + p["no_format"]
        return sum(r["count"] for r in p[pool_keys[group]])

    for group in ("domain", "format", "created_year"):
        assert pool_total(counts, group) <= pool_total(base, group), group


# ---------------------------------------------------------------------------
# Reports — count/list consistency + deterministic ordering (list
# statements order by `, id` when sort values tie)
# ---------------------------------------------------------------------------
def test_every_report_count_matches_list():
    for report in REPORTS:
        out = report_stmts(report)
        n = out["count"].get(*out["params"])["n"]
        rows = out["list"].all(*out["params"], 1_000_000, 0)
        assert n == len(rows), f"report {report['key']}: count {n} != list {len(rows)}"
        assert n >= 0


def test_every_report_deterministic_order():
    """Two runs give the same order — when sort values tie, the list
    statements order by `, id`."""
    for report in REPORTS:
        out = report_stmts(report)
        a = [tuple(r.items()) for r in out["list"].all(*out["params"], 500, 0)]
        b = [tuple(r.items()) for r in out["list"].all(*out["params"], 500, 0)]
        assert a == b, f"report {report['key']} order shuffled between runs"


def test_report_org_facet():
    """An org facet narrows the count. (The view validates bogus values
    against the facet options and ignores them — the query layer itself
    filters to whatever org_slug it's given.)"""
    report = next(r for r in REPORTS if r["key"] == "datasets-no-links")
    org_options = _report_counts(report, {}, "org")
    if not org_options:
        pytest.skip("no org facet options in the live data")
    slug = org_options[0]["slug"]
    total = report_stmts(report)["count"].get()["n"]
    filtered = report_stmts(report, {"org": slug})
    fcount = filtered["count"].get(*filtered["params"])["n"]
    assert fcount <= total
    assert fcount > 0


def _report_counts(report, filters, key):
    sql, params = report_facet_counts(report, filters)[key]
    return Query(sql).all(*params)


def test_report_facet_counts_shape():
    """Every faceted report's counts_sql compiles and executes — each facet
    key resolves to a per-report (sql, params) pair with non-empty options."""
    for report in REPORTS:
        facets = report.get("facets", [])
        if not facets:
            continue
        stmts = report_facet_counts(report, {})
        assert set(stmts) == {f["key"] for f in facets}, report["key"]
        for key in stmts:
            rows = _report_counts(report, {}, key)
            assert isinstance(rows, list), f"{report['key']}.{key}"
            assert rows, f"{report['key']}.{key} has no options"


def test_has_api_facets_self_exclude():
    """datasets-has-api's org and api_type facets self-exclude against each
    other — the multi-facet report (the fixed counts ignored the other
    filter entirely). Each facet's counts apply the other's filter, so the
    pools shrink and the org pool sums to the report count with the
    api_type filter set."""
    report = next(r for r in REPORTS if r["key"] == "datasets-has-api")

    def pool(filters, key):
        sql, params = report_facet_counts(report, filters)[key]
        return Query(sql).all(*params)

    org_opts = pool({}, "org")
    type_opts = pool({}, "api_type")
    if not org_opts or not type_opts:
        pytest.skip("no has-api facet options in the live data")
    org_slug = org_opts[0]["slug"]
    api_type = type_opts[0]["slug"]

    # org facet under api_type: every has-api dataset of that type belongs
    # to an org, so the pool sums to the report count with api_type set —
    # and the chosen org's count shrinks to its type-specific one.
    org_pool = pool({"api_type": api_type}, "org")
    stmt = report_stmts(report, {"api_type": api_type})
    assert sum(o["count"] for o in org_pool) == stmt["count"].get(*stmt["params"])["n"]
    unfiltered_org = {o["slug"]: o["count"] for o in org_opts}
    assert {o["slug"]: o["count"] for o in org_pool}.get(org_slug, 0) <= unfiltered_org[org_slug]

    # api_type facet under org: a dataset can match several types, so the
    # pool sum is an upper bound on the report count with org set — and the
    # chosen type's count shrinks to this org's own.
    type_pool = pool({"org": org_slug}, "api_type")
    stmt2 = report_stmts(report, {"org": org_slug})
    assert sum(t["count"] for t in type_pool) >= stmt2["count"].get(*stmt2["params"])["n"]
    unfiltered_type = {t["slug"]: t["count"] for t in type_opts}
    assert {t["slug"]: t["count"] for t in type_pool}.get(api_type, 0) <= unfiltered_type[api_type]


# ---------------------------------------------------------------------------
# Series list builder + yearly helpers
# ---------------------------------------------------------------------------
def test_series_list_stmt():
    for sort, dir_ in [
        ("dataset_count", "desc"),
        ("root_title", "asc"),
        ("org_count", "desc"),
        ("type", "asc"),
    ]:
        rows = series_list_stmt(sort, dir_).all(50, 0)
        assert len(rows) <= 50
        if rows:
            for col in ("id", "root_title", "dataset_count", "org_count", "type"):
                assert col in rows[0], f"series row missing {col}"


def test_yearly_helpers():
    org = org_created_years()
    ds = dataset_created_years()
    assert isinstance(org, list)
    assert isinstance(ds, list)
    if org:
        assert isinstance(org[0], str)
    if ds:
        assert isinstance(ds[0], str)


def test_metadata_values_pagination():
    full_key = METADATA_KEYS.all()[0]["key"]
    total_row = METADATA_VALUE_COUNT.get(full_key)
    assert total_row is not None
    total = total_row["n"]
    page1 = METADATA_VALUES.all(full_key, 100, 0)
    assert len(page1) == min(100, total)
    if total > 100:
        page2 = METADATA_VALUES.all(full_key, 100, 100)
        assert page2
        assert page2[0]["value"] != page1[0]["value"]
    assert METADATA_VALUES.all(full_key, 100, 10_000_000) == []


# ---------------------------------------------------------------------------
# Reviews helpers (DB-backed dedup)
# ---------------------------------------------------------------------------
def test_latest_reviews_dedup_semantics():
    rows = latest_reviews()
    assert len(rows) > 0
    ids = [r["dataset_id"] for r in rows]
    assert len(ids) == len(set(ids)), "latest_reviews must dedup to one per dataset"
    assert all(r.get("ok") is True for r in rows), "only ok:true records survive"
    # Every reviewed dataset id resolves in dataset_json (psycopg adapts a
    # Python list to a Postgres array for ANY(%s)).
    found = {row["id"] for row in Query("SELECT id FROM dataset_json WHERE id = ANY(%s)").all(ids)}
    assert found == set(ids), "every reviewed dataset resolves in dataset_json"


def test_get_review_returns_latest():
    """get_review(dataset_id) returns the record latest_reviews carries for
    that dataset (the same dedup source the views read)."""
    rows = latest_reviews()
    sample = rows[0]
    rev = get_review(sample["dataset_id"])
    assert rev is not None
    assert rev["dataset_id"] == sample["dataset_id"]
    # Latest per dataset — the DB stores one row per dataset (ingest
    # dedups), so the record round-trips exactly.
    assert rev == sample


def test_get_classification_is_get_review():
    """get_classification is an alias of get_review."""
    assert get_classification is get_review


def test_get_review_missing():
    assert get_review("__no_such_dataset__") is None
    assert get_classification("__no_such_dataset__") is None

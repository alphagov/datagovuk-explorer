"""Organisation statements — the fixed queries against the
organisations/datasets tables the org pages and home dashboard build
on, plus the DB-backed yearly-org-count helper and the self-excluding
SQL facet pools for /organisations' sidebar.

The DB is a build-time snapshot, so the fixed parameterless fetches
(org rows, per-org dataset aggregates, yearly counts) are memoised via
functools.cache — computed once per process, then served from memory.
The /organisations page is the slowest of the facet pages because its
per-org aggregate over datasets (ORG_AGGREGATES) and the last-published-year pool's
embedded subquery each scan the whole datasets table (~290ms per
request before memoisation). Restart the process to refresh after a DB
rebuild (same contract as the dashboard's cards() cache).

Only the *fixed* fetches are memoised: filtered facet pools stay live
because their filter key space is unbounded (last_published_year is a multi-select).
The raw Query objects (ORGS, ORG_AGGREGATES, ...) stay uncached so any
parameterised use elsewhere is unaffected.

The /organisations page *list* is a per-request SQL builder
(organisations_stmts — count + one page per filter/sort combo,
docs/pagination-plan.md workstream F); the memoised fetches still feed
the facet master lists, the pub-year validation whitelist and the
sidebar pools."""

import functools
from typing import Any

from explorer.buckets import BUCKET_EDGES, bucket_case, bucket_pairs, bucket_ranges, bucket_tests
from explorer.helpers import yearly_counts

from .core import Query, cached_unfiltered, facet_where

# Dataset-count facet buckets — 0 plus fixed ranges covering the full
# spread (orgs are heavily skewed small, so the low end is fine-grained).
# The edges and their derivation live in explorer/buckets (shared with the
# /datasets Links facet and /harvesters' per-source bucket), so a bucket
# key means the same range on every page; this module keeps the
# DATASET_BUCKET_* names the views/tests/harvesters import.
DATASET_BUCKET_EDGES = BUCKET_EDGES
DATASET_BUCKETS = bucket_pairs()
DATASET_BUCKET_NAMES = dict(DATASET_BUCKETS)
VALID_DATASET_BUCKETS = set(DATASET_BUCKET_NAMES)
DATASET_BUCKET_RANGES = bucket_ranges()

# The bucket membership tests — the reference semantics the SQL bucket
# clauses must match (dataset_count is package_count or 0, exactly like
# the SQL COALESCE below). Consumed by the facet-pool reference tests and
# the /harvesters page's bucket helper (the org list's own filtering is
# SQL since workstream F).
DATASET_BUCKET_TESTS = bucket_tests()

# CASE expression mapping COALESCE(package_count, 0) to its bucket key —
# generated from the shared ranges so the SQL boundaries can't drift.
_DATASET_BUCKET_CASE = bucket_case("COALESCE(o.package_count, 0)")


# All organisations, in display-name order
ORGS = Query(
    """SELECT slug, name, display_name, package_count, type, state,
              approval_status, created, title
         FROM organisations
         ORDER BY LOWER(display_name), slug""",
)

# One organisation
ORG = Query(
    """SELECT slug, name, display_name, package_count, type, state,
              approval_status, created, title
         FROM organisations WHERE slug = %s""",
)

# Per-org aggregates over datasets — one pass over the table. Any
# org_slug present here has at least one dataset, so it doubles as the
# fetched-slugs set.
ORG_AGGREGATES = Query(
    """SELECT org_slug,
              SUM(resource_count) AS total_resources,
              SUM(views) AS total_views,
              MAX(metadata_created) AS last_published
       FROM datasets GROUP BY org_slug""",
)

# Total resources per org
RESOURCE_COUNTS = Query(
    """SELECT org_slug, SUM(resource_count) AS total
       FROM datasets GROUP BY org_slug""",
)

# Total views per org
VIEWS_BY_ORG = Query(
    """SELECT org_slug, SUM(views) AS total
       FROM datasets GROUP BY org_slug""",
)

# Most recent dataset publication timestamp per org
LAST_PUBLISHED_BY_ORG = Query(
    """SELECT org_slug, MAX(metadata_created) AS last_published
       FROM datasets WHERE metadata_created IS NOT NULL
       GROUP BY org_slug""",
)


# Orgs created per year (YYYY) — created is always ISO, so
# substr(created, 1, 4) is the year; the regex skips anything non-ISO.
YEARLY_ORGS = Query(
    r"""SELECT substr(created, 1, 4) AS year, COUNT(*) AS count
       FROM organisations WHERE created ~ '^\d{4}'
       GROUP BY substr(created, 1, 4)""",
)


@functools.cache
def all_org_rows() -> list[dict[str, Any]]:
    """All organisations (ORGS.all) — memoised: build-time snapshot."""
    return ORGS.all()


@functools.cache
def org_aggregate_rows() -> list[dict[str, Any]]:
    """One-pass per-org aggregates over datasets (ORG_AGGREGATES.all) —
    memoised: build-time snapshot. The dominant cost on /organisations."""
    return ORG_AGGREGATES.all()


@functools.cache
def yearly_org_counts() -> list[dict[str, Any]]:
    """Count organisations created per year (YYYY), continuous from first
    to last year — memoised: build-time snapshot."""
    return yearly_counts(YEARLY_ORGS.all())


# --- /organisations sidebar facet pools (self-excluding SQL aggregates) ---
#
# Each group counts over the pool filtered by the other two groups via the
# shared core.facet_where helper — the same one-sentence algorithm as
# /datasets, expressed over organisations joined to a per-org
# last-published aggregation of datasets. The list/filter/sort moved to
# SQL too (organisations_stmts below); the pools still run as SQL
# aggregates here, not Python filters.

# Per-org aggregate over datasets — the LEFT JOIN base the facet pools
# and the /organisations list builder share. Same three aggregates as
# ORG_AGGREGATES (one 1:1 row per org: GROUP BY org_slug, the primary
# key). The facet pools only read a.last_published; the list builder
# reads total_resources/total_views too.
_ORG_AGG = (
    "LEFT JOIN ("
    "  SELECT org_slug,"
    "         SUM(resource_count) AS total_resources,"
    "         SUM(views) AS total_views,"
    "         MAX(metadata_created) AS last_published"
    "  FROM datasets GROUP BY org_slug"
    ") a ON a.org_slug = o.slug"
)

# Pool guards: the \d{4} created-year skip (created is always ISO) and
# the last-published IS NOT NULL skip (orgs with no datasets land in no
# last-published-year bucket).
_YEAR_CREATED_GUARD = r"substr(o.created, 1, 4) ~ '^\d{4}'"
_PUB_YEAR_GUARD = "a.last_published IS NOT NULL"


def _created_year_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    """created_year WHERE fragment + params, or ([], []) when skipped/
    excluded (the org's creation year, o.created)."""
    if exclude == "created_year":
        return [], []
    year = filters.get("created_year")
    if year:
        return ["substr(o.created, 1, 4) = %s"], [year]
    return [], []


def _last_published_year_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    """last_published_year (multi-select) WHERE fragment + params, or
    ([], []) when skipped/excluded. Matches orgs whose MAX(metadata_created)
    year is one of the selected years — the view's
    o["last_published_year"] in filters.last_published_years check. __none__
    is the never-published selection (orgs with no datasets →
    a.last_published NULL)."""
    if exclude == "last_published_year":
        return [], []
    pub_years = filters.get("last_published_year")
    if pub_years:
        if "__none__" in pub_years:
            return ["a.last_published IS NULL"], []
        return ["substr(a.last_published, 1, 4) = ANY(%s)"], [list(pub_years)]
    return [], []


def _datasets_bucket_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    """datasets (dataset-count bucket) WHERE fragment + params, or ([], [])
    when skipped/excluded. Boundaries come from DATASET_BUCKET_RANGES — the
    same edges as the Python tests, with package_count COALESCE'd to 0 to
    mirror the view's `or 0`."""
    if exclude == "datasets":
        return [], []
    bucket = filters.get("datasets")
    if bucket:
        lo, hi = DATASET_BUCKET_RANGES[bucket]
        col = "COALESCE(o.package_count, 0)"
        if hi is None:
            return [f"{col} > %s"], [lo]
        return [f"{col} BETWEEN %s AND %s"], [lo, hi]
    return [], []


# The three clause builders keyed by facet — the dict core.facet_where
# ANDs together (minus the excluded facet) for the pools.
_ORG_FACET_CLAUSES = {
    "created_year": _created_year_clause,
    "last_published_year": _last_published_year_clause,
    "datasets": _datasets_bucket_clause,
}


def _org_facet_counts(filters: dict) -> dict:
    """Compiled facet-count statements for one (created_year/
    last_published_year/datasets) combo — the {created_years,
    last_published_years, no_last_published_year, datasets} Queries plus
    per-statement params."""
    year_where, year_params = facet_where(_ORG_FACET_CLAUSES, filters, exclude="created_year")
    pubyear_frag, pubyear_params = facet_where(
        _ORG_FACET_CLAUSES,
        filters,
        exclude="last_published_year",
    )
    datasets_where, datasets_params = facet_where(_ORG_FACET_CLAUSES, filters, exclude="datasets")

    # The pool guards join the (possibly empty) WHERE fragments. `no_last_\
    # published_year` reuses the pubyear fragment (the other groups'
    # filters) with the guard flipped — last_published IS NULL (orgs with
    # no datasets) instead of the year-list guard's IS NOT NULL.
    year_where = f"{year_where} AND {_YEAR_CREATED_GUARD}" if year_where else f" WHERE {_YEAR_CREATED_GUARD}"
    pubyear_where = f"{pubyear_frag} AND {_PUB_YEAR_GUARD}" if pubyear_frag else f" WHERE {_PUB_YEAR_GUARD}"
    no_pubyear_where = (
        f"{pubyear_frag} AND a.last_published IS NULL" if pubyear_frag else " WHERE a.last_published IS NULL"
    )

    entry = {
        "params": {
            "created_years": year_params,
            "last_published_years": pubyear_params,
            "no_last_published_year": pubyear_params,
            "datasets": datasets_params,
        },
        "created_years": Query(
            "SELECT substr(o.created, 1, 4) AS created_year, COUNT(*) AS count"
            f" FROM organisations o {_ORG_AGG}{year_where}"
            " GROUP BY substr(o.created, 1, 4)",
        ),
        "last_published_years": Query(
            "SELECT substr(a.last_published, 1, 4) AS last_published_year, COUNT(*) AS count"
            f" FROM organisations o {_ORG_AGG}{pubyear_where}"
            " GROUP BY substr(a.last_published, 1, 4)",
        ),
        "no_last_published_year": Query(
            f"SELECT COUNT(*) AS n FROM organisations o {_ORG_AGG}{no_pubyear_where}",
        ),
        # One pass over the (1:1-joined) org rows; every org lands in exactly
        # one bucket via the ELSE top.
        "datasets": Query(
            f"SELECT {_DATASET_BUCKET_CASE} AS bucket, COUNT(*) AS count"
            f" FROM organisations o {_ORG_AGG}{datasets_where}"
            " GROUP BY 1",
        ),
    }
    return entry


def _run_facet_counts(filters: dict) -> dict:
    """Compile + fetch the three self-excluding sidebar pools for one
    (created_year/last_published_year/datasets) filter combo."""
    entry = _org_facet_counts(filters)
    p = entry["params"]
    return {
        "created_years": entry["created_years"].all(*p["created_years"]),
        "last_published_years": entry["last_published_years"].all(*p["last_published_years"]),
        "no_last_published_year": (entry["no_last_published_year"].get(*p["no_last_published_year"]) or {}).get("n", 0),
        "datasets": entry["datasets"].all(*p["datasets"]),
    }


@cached_unfiltered
def organisations_facet_counts(filters: dict) -> dict:
    """Sidebar facet counts for /organisations — each group counts over the
    pool filtered by the other two groups (self-excluding). Returns:

      'created_years':         [{'created_year': 'YYYY', 'count': n}, ...]
      'last_published_years':  [{'last_published_year': 'YYYY', 'count': n}, ...]
      'no_last_published_year': int — orgs with no last-published year (the
                               "Never published" trailing bucket)
      'datasets':              [{'bucket': '0'|'1-10'|..., 'count': n}, ...]

    No-filter calls (the common view) return the memoised unfiltered pools
    via core.cached_unfiltered; only calls with an active filter run the SQL
    live (their key space is unbounded, so they can't be cached).
    """
    return _run_facet_counts(filters)


# ── /organisations list builder (count + one page per filter/sort combo) ──
#
# The list used to be filtered/sorted in Python over the merged memoised
# fetch (1,480 orgs, docs/pagination-plan.md workstream F); now the page
# list/count are SQL — the ORGS rows LEFT JOINed to the per-org aggregate,
# with the view's old Python _apply_filters rules as WHERE clauses
# (created_year/last_published_year/datasets via the shared
# _ORG_FACET_CLAUSES) and the
# sort_orgs column exprs as ORDER BY.
#
# The `, LOWER(o.display_name), o.slug` tail reproduces the old
# stable-sort tie order: Python's list.sort is stable over the base fetch
# (ORGS is ORDER BY LOWER(display_name), slug), so rows tied on any sort
# key keep that order — the SQL ORDER BY appends the same two keys,
# pinning pages against reshuffles. created/last_published sort on the
# raw ISO timestamp: the old Python sorter sorted the *formatted*
# dd/mm/yyyy string (day-then-month-then-year, not chronological) — the
# ISO sort is the intended semantics (same call as the harvesters
# last_run sort).

# Sortable column key → SQL ORDER BY expression (mirrors
# explorer.sort.sort_orgs: the numeric columns sort COALESCE'd to 0 —
# missing sorts as 0, exactly like Python's `or 0` — and the text
# columns sort case-insensitively via LOWER).
ORG_SORT_EXPRS = {
    "name": "LOWER(COALESCE(o.display_name, o.title, o.name, ''))",
    "dataset_count": "COALESCE(o.package_count, 0)",
    "resource_count": "COALESCE(a.total_resources, 0)",
    "views": "COALESCE(a.total_views, 0)",
    "type": "LOWER(COALESCE(o.type, ''))",
    "state": "LOWER(COALESCE(o.state, ''))",
    "approval_status": "LOWER(COALESCE(o.approval_status, ''))",
    "created": "COALESCE(o.created, '')",
    "last_published": "COALESCE(a.last_published, '')",
}

# The list select — ORGS' columns plus the three aggregate columns and a
# has_data flag (an org is in the per-dataset aggregate iff it has at
# least one dataset — the old fetched-slugs set).
_ORG_LIST_SELECT = (
    "SELECT o.slug, o.name, o.display_name, o.package_count, o.type, o.state,"
    "       o.approval_status, o.created, o.title,"
    "       COALESCE(a.total_resources, 0) AS total_resources,"
    "       COALESCE(a.total_views, 0) AS total_views,"
    "       a.last_published,"
    "       (a.org_slug IS NOT NULL) AS has_data"
    " FROM organisations o"
)


def organisations_stmts(filters: dict, sort: str, dir_: str) -> dict:
    """Count + page list for /organisations — one (filters, sort, dir) combo.

    {params, count, list} contract, same as datasets_stmts: the view drives
    the LIMIT/OFFSET page with core.paginate(). The WHERE clauses mirror the
    old Python _apply_filters rules (year/pubyear/datasets), the ORDER BY
    mirrors sort_orgs, and the aggregate LEFT JOIN is 1:1 per org, so the
    count is a plain COUNT over the joined rows."""
    where, params = facet_where(_ORG_FACET_CLAUSES, filters)
    order_sql = f"{ORG_SORT_EXPRS[sort]} {'DESC' if dir_ == 'desc' else 'ASC'}, LOWER(o.display_name), o.slug"
    return {
        "params": params,
        "count": Query(f"SELECT COUNT(*) AS n FROM organisations o {_ORG_AGG}{where}"),
        "list": Query(f"{_ORG_LIST_SELECT} {_ORG_AGG}{where} ORDER BY {order_sql} LIMIT %s OFFSET %s"),
    }

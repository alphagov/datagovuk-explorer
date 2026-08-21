"""/datasets query builder — count/list statements compiled per
(filters, sort, dir)."""

import functools
from datetime import UTC, datetime
from typing import Any

from explorer.helpers import yearly_counts

from .core import Query, cached_unfiltered, facet_where, fetch_parallel

# --- /datasets query builder ---
#
# Compiled per (filters, sort, dir). filters: { theme, source, year,
# temporal, metadata_key, metadata_value }.
#
# The WHERE clauses drive the page list + count (filtering, sorting and
# pagination happen in the database instead of sorting the whole table in
# Python on every request), and the sidebar facet counts use the same
# builder with their own group excluded — one clause builder, both
# consumers, so the counts can't drift from the list.

# Temporal-year facet window. Years inside [TEMPORAL_MIN_YEAR, current year]
# are listed individually — every covered year, not just range boundaries,
# so a dataset covering 1981-2009 counts for 2000 too. Coverage outside the
# window collapses into "Before 1900" (historic/junk) and "After <year>"
# (future-dated junk) buckets. The upper bound derives from the current year
# so the window tracks new data without a code change. Both are interpolated
# as literals: they are code constants, never user input.
TEMPORAL_MIN_YEAR = 1900
TEMPORAL_MAX_YEAR = datetime.now(UTC).year

# Sortable column key → SQL ORDER BY expression. Text columns use LOWER for
# case-insensitive sort; numeric columns sort numerically. `organisation` is
# org_display_name, `resources` is resource_count.
DATASETS_SORT_EXPRS = {
    "title": "LOWER(COALESCE(d.title, ''))",
    "organisation": "LOWER(COALESCE(d.org_display_name, ''))",
    "metadata_created": "COALESCE(d.metadata_created, '')",
    "metadata_modified": "COALESCE(d.metadata_modified, '')",
    "resources": "COALESCE(d.resource_count, 0)",
    "views": "COALESCE(d.views, 0)",
    "harvested": "COALESCE(d.harvested, 0)",
}

# Temporal coverage: temporal_periods rows are [from_year, to_year]
# (either year NULL for open-ended coverage) with a source column
# ('declared' | 'title' | 'resource'). A dataset covers year Y when some
# period has (from_year IS NULL OR from_year <= Y) AND (to_year IS NULL OR
# to_year >= Y).
COVERS_YEAR_CLAUSE = """
  EXISTS (
    SELECT 1 FROM temporal_periods tp
    WHERE tp.dataset_id = d.id
      AND (tp.from_year IS NULL OR tp.from_year <= %s)
      AND (tp.to_year IS NULL OR tp.to_year >= %s)
  )"""

# Earliest covered year across all periods predates the window
COVERS_BEFORE_CLAUSE = f"""
  EXISTS (
    SELECT 1 FROM temporal_periods tp
    WHERE tp.dataset_id = d.id
      AND COALESCE(tp.from_year, tp.to_year) < {TEMPORAL_MIN_YEAR}
  )"""

# Latest covered year across all periods is beyond the window
COVERS_AFTER_CLAUSE = f"""
  EXISTS (
    SELECT 1 FROM temporal_periods tp
    WHERE tp.dataset_id = d.id
      AND COALESCE(tp.to_year, tp.from_year) > {TEMPORAL_MAX_YEAR}
  )"""


def _metadata_clause(filters: dict) -> tuple[str, list]:
    """WHERE fragment + params for the metadata_key/metadata_value filter.

    `->>` returns text for present keys and NULL for missing ones; empty
    objects/arrays become the strings '[]' / '{}'.
    """
    key = filters["metadata_key"]
    value = filters["metadata_value"]
    section, field_name = key.split(":", 1)
    if value == "(empty)":
        if section == "top":
            clause = "(dj.json->>%s IS NULL OR dj.json->>%s = '' OR dj.json->>%s = '[]' OR dj.json->>%s = '{}')"
            return clause, [field_name] * 4
        clause = (
            "(NOT EXISTS (SELECT 1 FROM jsonb_array_elements(dj.json->'extras') "
            "AS elem WHERE elem->>'key' = %s) "
            "OR EXISTS (SELECT 1 FROM jsonb_array_elements(dj.json->'extras') "
            "AS elem WHERE elem->>'key' = %s AND (elem->>'value' IS NULL "
            "OR elem->>'value' = '' OR elem->>'value' = '[]' OR elem->>'value' = '{}')))"
        )
        return clause, [field_name, field_name]
    if section == "top":
        return "dj.json->>%s = %s", [field_name, value]
    clause = (
        "EXISTS (SELECT 1 FROM jsonb_array_elements(dj.json->'extras') "
        "AS elem WHERE elem->>'key' = %s AND elem->>'value' = %s)"
    )
    return clause, [field_name, value]


def _theme_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    """theme WHERE fragment + params, or ([], []) when skipped/excluded."""
    if exclude == "theme":
        return [], []
    theme = filters.get("theme")
    if theme == "none":
        return ["d.theme_primary IS NULL"], []
    if theme:
        return ["d.theme_primary = %s"], [theme]
    return [], []


def _source_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    """source WHERE fragment + params, or ([], []) when skipped/excluded."""
    if exclude == "source":
        return [], []
    source = filters.get("source")
    if source == "harvested":
        return ["d.harvested = 1"], []
    if source == "manual":
        return ["d.harvested = 0"], []
    return [], []


def _year_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    """year WHERE fragment + params, or ([], []) when skipped/excluded."""
    if exclude == "year":
        return [], []
    year = filters.get("year")
    if year:
        return ["substr(d.metadata_created, 1, 4) = %s"], [year]
    return [], []


def _temporal_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    """temporal WHERE fragment + params, or ([], []) when skipped/excluded."""
    if exclude == "temporal":
        return [], []
    temporal = filters.get("temporal")
    if temporal == "none":
        return [
            "NOT EXISTS (SELECT 1 FROM temporal_periods tp WHERE tp.dataset_id = d.id)",
        ], []
    if temporal == "pre1900":
        return [COVERS_BEFORE_CLAUSE], []
    if temporal == "post":
        return [COVERS_AFTER_CLAUSE], []
    if temporal:
        y = int(temporal)
        return [COVERS_YEAR_CLAUSE], [y, y]
    return [], []


# The four /datasets clause builders, keyed by facet — the dict
# core.facet_where ANDs together (minus the excluded facet) for both the
# page list/count and the sidebar facet pools.
_FACET_CLAUSES = {
    "theme": _theme_clause,
    "source": _source_clause,
    "year": _year_clause,
    "temporal": _temporal_clause,
}


def _facet_where(filters: dict, exclude: str | None = None) -> tuple[str, list]:
    """WHERE fragment + params for the theme/source/year/temporal filters,
    omitting `exclude` (the facet group being counted).

    The metadata filter is deliberately not handled here — it applies to the
    page list/count only, never to the facet counts (contract item 1), so
    `datasets_stmts` adds its clause after this. Routed through the shared
    core.facet_where helper with the four clause builders above.
    """
    return facet_where(_FACET_CLAUSES, filters, exclude)


def datasets_stmts(filters: dict, sort: str, dir_: str) -> dict:
    """Return { count, list, params } for one (filters, sort, dir) combo.

    The facet WHERE comes from `_facet_where`; the metadata filter joins it
    here (list/count only — facet counts deliberately ignore it).
    """
    where, params = _facet_where(filters)
    meta_join = ""
    if filters.get("metadata_key") and filters.get("metadata_value") is not None:
        meta_join = " JOIN dataset_json dj ON dj.id = d.id"
        clause, meta_params = _metadata_clause(filters)
        where = f"{where} AND {clause}" if where else f" WHERE {clause}"
        params = [*params, *meta_params]
    # `, d.id` tiebreak pins tied rows to id order — an unpinned ORDER BY
    # would reshuffle pages whenever rows tie on the sort key. It only
    # affects ties; the primary ordering is unchanged.
    order_sql = f"{DATASETS_SORT_EXPRS[sort]} {'DESC' if dir_ == 'desc' else 'ASC'}, d.id"

    entry = {
        "params": params,
        "count": Query(f"SELECT COUNT(*) AS n FROM datasets d{meta_join}{where}"),
        "list": Query(
            "SELECT d.id, d.title, d.name, d.org_slug,"
            "  d.org_display_name AS organisation,"
            "  d.metadata_created, d.metadata_modified, d.resource_count,"
            "  d.theme_primary, d.harvested, d.harvest_source_title, d.views"
            f" FROM datasets d{meta_join}{where}"
            f" ORDER BY {order_sql}"
            " LIMIT %s OFFSET %s",
        ),
    }
    return entry


def org_datasets_stmts(org_slug: str, sort: str, dir_: str) -> dict:
    """Count + page list for one org's datasets — the /organisation/{slug}
    page (docs/pagination-plan.md workstream E).

    Same {params, count, list} contract as datasets_stmts: one fixed org
    param, the DATASETS_SORT_EXPRS ORDER BY with the `, d.id` tiebreak
    (pins rows tied on the sort key to id order, so pages don't reshuffle),
    and a LIMIT/OFFSET page the view drives with core.paginate(). The org
    page used to fetch every row and sort in Python (up to 5.6k for ONS);
    now it fetches one page of 100.
    """
    order_sql = f"{DATASETS_SORT_EXPRS[sort]} {'DESC' if dir_ == 'desc' else 'ASC'}, d.id"
    return {
        "params": [org_slug],
        "count": Query("SELECT COUNT(*) AS n FROM datasets d WHERE d.org_slug = %s"),
        "list": Query(
            "SELECT d.id, d.title, d.name, d.metadata_created,"
            "  d.metadata_modified, d.resource_count,"
            "  d.harvested, d.harvest_source_title, d.views"
            " FROM datasets d WHERE d.org_slug = %s"
            f" ORDER BY {order_sql}"
            " LIMIT %s OFFSET %s",
        ),
    }


def source_datasets_stmts(source_id: str, sort: str, dir_: str) -> dict:
    """Count + page list for one harvest source's datasets — the
    /harvester/{id} page (docs/pagination-plan.md workstream E).

    Same {params, count, list} contract as org_datasets_stmts, joined by
    harvest_source_id (the datasets↔sources key promoted from the dataset's
    harvest_source_id extra — the same join the /harvesters list uses;
    titles aren't unique across sources, so title joins overcount). All of
    these datasets are harvested by definition, so no harvested column: the
    source page shows Title/Created/Updated/Resources/Views.
    """
    order_sql = f"{DATASETS_SORT_EXPRS[sort]} {'DESC' if dir_ == 'desc' else 'ASC'}, d.id"
    return {
        "params": [source_id],
        "count": Query("SELECT COUNT(*) AS n FROM datasets d WHERE d.harvest_source_id = %s"),
        "list": Query(
            "SELECT d.id, d.org_slug, d.title, d.name, d.metadata_created,"
            "  d.metadata_modified, d.resource_count, d.views"
            " FROM datasets d WHERE d.harvest_source_id = %s"
            f" ORDER BY {order_sql}"
            " LIMIT %s OFFSET %s",
        ),
    }


# --- Sidebar facet counts (SQL aggregates over the same _facet_where) ---
#
# Metadata filters are deliberately not applied to any pool: facet counts
# never react to the metadata filter (contract item 1) — only the page
# list/count applies it.


def _facet_counts(filters: dict) -> dict:
    """Compiled facet-count statements for one (theme/source/year/temporal)
    combo — the {themes, source, years, temporal_years, temporal_buckets}
    Queries plus the per-statement params."""
    theme_where, theme_params = _facet_where(filters, exclude="theme")
    source_where, source_params = _facet_where(filters, exclude="source")
    year_where, year_params = _facet_where(filters, exclude="year")
    temporal_where, temporal_params = _facet_where(filters, exclude="temporal")

    # metadata_created IS NOT NULL joins the (possibly empty) where fragment
    year_where = (
        f"{year_where} AND d.metadata_created IS NOT NULL" if year_where else " WHERE d.metadata_created IS NOT NULL"
    )

    entry = {
        "params": {
            "themes": theme_params,
            "source": source_params,
            "years": year_params,
            "temporal_years": temporal_params,
            "temporal_buckets": temporal_params,
        },
        "themes": Query(
            "SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count"
            f" FROM datasets d{theme_where}"
            " GROUP BY COALESCE(theme_primary, '__none__')",
        ),
        "source": Query(
            "SELECT COUNT(*) FILTER (WHERE harvested = 1) AS harvested,"
            "       COUNT(*) FILTER (WHERE harvested = 0) AS manual"
            f" FROM datasets d{source_where}",
        ),
        "years": Query(
            "SELECT substr(metadata_created, 1, 4) AS year, COUNT(*) AS count"
            f" FROM datasets d{year_where}"
            " GROUP BY substr(metadata_created, 1, 4)",
        ),
        # Per-year counts via the periods table + clamped expansion: a
        # dataset covering 1981-2009 counts for every in-window year.
        # generate_series degenerates to zero rows for periods entirely
        # outside the window (GREATEST > LEAST → empty), and single-element
        # periods [2005, null] collapse to generate_series(2005, 2005) via
        # the COALESCE pairs. COUNT(DISTINCT d.id) keeps a dataset with
        # several periods covering the same year from counting 3x (the old
        # COUNT(*) over the jsonb unroll double-counted). Datasets with no
        # rows at all contribute to no year (they feed the `none` bucket).
        "temporal_years": Query(
            "SELECT y AS year, COUNT(DISTINCT d.id) AS count"
            " FROM temporal_periods tp"
            " JOIN datasets d ON d.id = tp.dataset_id"
            " CROSS JOIN LATERAL ("
            "   SELECT generate_series("
            "     GREATEST(COALESCE(tp.from_year, tp.to_year),"
            f"              {TEMPORAL_MIN_YEAR}),"
            "     LEAST(COALESCE(tp.to_year, tp.from_year),"
            f"             {TEMPORAL_MAX_YEAR})"
            "   ) AS y"
            " ) yrs"
            f"{temporal_where}"
            " GROUP BY y",
        ),
        # The three buckets in one pass. pre1900/post reuse the COVERS_*
        # predicate bodies; `none` is datasets with no period rows at all
        # (no declared and no inferred year). The pre1900 and post buckets
        # are independent filters, so a row can land in both.
        "temporal_buckets": Query(
            "SELECT"
            "  COUNT(*) FILTER (WHERE NOT EXISTS ("
            "    SELECT 1 FROM temporal_periods tp WHERE tp.dataset_id = d.id"
            "  )) AS none,"
            f"  COUNT(*) FILTER (WHERE {COVERS_BEFORE_CLAUSE}) AS pre1900,"
            f"  COUNT(*) FILTER (WHERE {COVERS_AFTER_CLAUSE}) AS post"
            f" FROM datasets d{temporal_where}",
        ),
    }
    return entry


@cached_unfiltered
def datasets_facet_counts(filters: dict) -> dict:
    """Sidebar facet counts for /datasets — every group counts over the pool
    filtered by the other groups, ignoring the metadata filter. Returns:

      'themes':          [{'theme': slug | '__none__', 'count': n}, ...]
      'source':          {'harvested': n, 'manual': n}
      'years':           [{'year': 'YYYY', 'count': n}, ...]
      'temporal_years':  [{'year': int, 'count': n}, ...]
      'temporal_buckets': {'pre1900': n, 'post': n, 'none': n}

    The five pools are five independent single-SELECT aggregates, so they
    run concurrently via core.fetch_parallel.

    No-filter calls (the common /datasets view) return the memoised
    unfiltered pools via core.cached_unfiltered — the temporal pools alone
    are ~250ms of scans — while filtered calls run live (their key space is
    unbounded, so they can't be cached).
    """
    entry = _facet_counts(filters)
    p = entry["params"]
    themes, source, years, temporal_years, temporal_buckets = fetch_parallel(
        [
            lambda: entry["themes"].all(*p["themes"]),
            lambda: entry["source"].get(*p["source"]),
            lambda: entry["years"].all(*p["years"]),
            lambda: entry["temporal_years"].all(*p["temporal_years"]),
            lambda: entry["temporal_buckets"].get(*p["temporal_buckets"]),
        ],
    )
    return {
        "themes": themes,
        "source": source,
        "years": years,
        "temporal_years": temporal_years,
        "temporal_buckets": temporal_buckets,
    }


# --- Fixed statements (the /datasets report, home dashboard, org pages
# and dataset detail page build on these) ---

# Orgs that have at least one fetched dataset
FETCHED_SLUGS = Query("SELECT DISTINCT org_slug FROM datasets")

# Total number of datasets
DATASET_TOTAL = Query("SELECT COUNT(*) AS n FROM datasets")

# Datasets harvested by a harvester (not created manually)
DATASETS_HARVESTED = Query("SELECT COUNT(*) AS n FROM datasets WHERE harvested = 1")

# Datasets created per year
YEARLY_DATASETS = Query(
    """SELECT substr(metadata_created, 1, 4) AS year, COUNT(*) AS count
       FROM datasets WHERE metadata_created IS NOT NULL
       GROUP BY substr(metadata_created, 1, 4)""",
)

# Datasets created per year for one org
YEARLY_BY_ORG = Query(
    """SELECT substr(metadata_created, 1, 4) AS year, COUNT(*) AS count
       FROM datasets WHERE org_slug = %s AND metadata_created IS NOT NULL
       GROUP BY substr(metadata_created, 1, 4)""",
)

# Datasets per primary theme
THEME_COUNTS = Query(
    """SELECT COALESCE(theme_primary, '__none__') AS theme, COUNT(*) AS count
       FROM datasets GROUP BY COALESCE(theme_primary, '__none__')""",
)

# In-window covered temporal years (validation of ?temporal=) —
# filter-independent, latest first. generate_series over the periods table
# clamps coverage to [TEMPORAL_MIN_YEAR, TEMPORAL_MAX_YEAR] exactly as the
# facet pools do.
TEMPORAL_YEARS = Query(
    f"""SELECT DISTINCT y AS year FROM (
      SELECT generate_series(
        GREATEST(COALESCE(tp.from_year, tp.to_year), {TEMPORAL_MIN_YEAR}),
        LEAST(COALESCE(tp.to_year, tp.from_year), {TEMPORAL_MAX_YEAR})
      ) AS y
      FROM temporal_periods tp
    ) covers
    ORDER BY year DESC""",
)

# Dataset count for one org
DATASET_COUNT = Query("SELECT COUNT(*) AS count FROM datasets WHERE org_slug = %s")

# Harvested datasets for one org — the org page's second headline count
# (pagination-plan workstream E: was a Python sum over the unfetched full
# dataset list, now its own COUNT).
ORG_HARVESTED_COUNT = Query(
    "SELECT COUNT(*) AS n FROM datasets WHERE org_slug = %s AND harvested = 1",
)

# Full dataset JSON for the detail page
DATASET_JSON = Query("SELECT json FROM dataset_json WHERE id = %s")

# Normalised coverage periods for the detail page (position order). The
# view shows declared-source rows under the raw-JSON From/To display and
# suggested rows ('title'/'resource') as a separate "suggested" section.
DATASET_TEMPORAL_PERIODS = Query(
    "SELECT from_year, to_year, source FROM temporal_periods WHERE dataset_id = %s ORDER BY position",
)

# Full-text "more like this" via tsvector, with series exclusion: datasets
# in the same detected series as the current one are not "related".
RELATED_BY_FTS = Query(
    """WITH q AS (
         SELECT websearch_to_tsquery('english', %s) AS q
       )
       SELECT id, title, org_slug, org_display_name, theme_primary, rank
       FROM (
         SELECT d.id, d.title, d.org_slug, d.org_display_name, d.theme_primary,
                ts_rank(d.fts, q.q) AS rank,
                ROW_NUMBER() OVER (PARTITION BY d.org_slug ORDER BY ts_rank(d.fts, q.q) DESC, d.id) AS rn
         FROM datasets d, q
         WHERE d.fts @@ q.q
           AND d.id != %s
           AND d.id NOT IN (
             SELECT sd.dataset_id FROM series_datasets sd
             WHERE sd.series_id IN (
               SELECT sd2.series_id FROM series_datasets sd2 WHERE sd2.dataset_id = %s
             )
           )
       ) sub
       WHERE rn <= 2
       ORDER BY rank DESC, id
       LIMIT 20""",
)


# ── Memoised fixed fetches ───────────────────────────────────────────────
# The fixed parameterless queries below are build-time snapshots, so they're
# memoised per process (restart to refresh after a rebuild — same contract
# as the dashboard's cards() cache). Only these accessors are cached; the
# raw Query objects stay live for parameterised use (detail pages, tests).


@functools.cache
def fetched_slugs() -> list[dict[str, Any]]:
    """Orgs that have at least one fetched dataset (FETCHED_SLUGS) — memoised."""
    return FETCHED_SLUGS.all()


@functools.cache
def harvested_count() -> int:
    """Datasets harvested vs manual (DATASETS_HARVESTED) — memoised."""
    return DATASETS_HARVESTED.get()["n"]


@functools.cache
def yearly_dataset_counts() -> list[dict[str, Any]]:
    """Count datasets created per year (YYYY), continuous from first to last year — memoised."""
    return yearly_counts(YEARLY_DATASETS.all())

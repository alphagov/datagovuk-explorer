"""Reviews / suggestions helpers — DB-backed, read from the `reviews`
table (populated by scripts/ingest_reviews.py from the JSONL)."""

import json
from functools import cache

from explorer.sort import order_by

from .core import Query, cached_unfiltered, facet_where, fetch_parallel

# ---------------------------------------------------------------------------
# Reviews / suggestions — DB-backed, read from the `reviews` table
# ---------------------------------------------------------------------------
# Only ok:true records count, and only the latest per dataset_id — later in
# the file = higher id (ingest inserts in file order). json is TEXT, so it
# comes back as a plain string the views json.loads.

# All ok reviews, one (latest) per dataset — DISTINCT ON keeps the
# highest-id (latest) record per dataset_id.
_LATEST_REVIEWS = Query(
    """SELECT json FROM (
      SELECT DISTINCT ON (dataset_id) dataset_id, id, json
      FROM reviews WHERE ok = true
      ORDER BY dataset_id, id DESC
    ) latest ORDER BY id""",
)

# Latest ok review for one dataset id.
_REVIEW_FOR = Query(
    "SELECT json FROM reviews WHERE ok = true AND dataset_id = %s ORDER BY id DESC LIMIT 1",
)


@cache
def latest_reviews() -> list[dict]:
    """All ok reviews, one (latest) per dataset."""
    return [json.loads(row["json"]) for row in _LATEST_REVIEWS.all()]


def _review_for(dataset_id: str) -> dict | None:
    """Latest ok review for one dataset id, or None."""
    rows = _REVIEW_FOR.all(dataset_id)
    if not rows:
        return None
    return json.loads(rows[0]["json"])


# Alias — get_classification is the same query as get_review.
get_review = _review_for
get_classification = _review_for


# --- /reviews query builder ---
#
# Compiled per (filters, sort, dir). filters: { overall, findability,
# metadata, resources } — a score value "0".."5" or "none" (missing
# score). Same pattern as datasets.py: the WHERE clauses drive the page
# list + count (filtering, sorting and pagination in the database instead
# of fetching + json.loads-ing every row in Python), and the sidebar facet
# counts use the same builder with their own group excluded — one clause
# builder, both consumers.

# The dedup subquery every statement below is built on — the latest ok
# review per dataset (see _LATEST_REVIEWS). Joining to `datasets` supplies
# the *current* title/org, not the review-time values in the JSON.
_DEDUP = """
    SELECT DISTINCT ON (dataset_id) id, dataset_id, overall,
           findability, metadata, resources
    FROM reviews WHERE ok = true ORDER BY dataset_id, id DESC
"""

# Score dimensions — one facet group per dimension, mirroring the sortable
# columns. overall lives at the top level of a review; the others are the
# denormalised subscore columns the ingest populates. A missing score is
# represented by the "none" facet.
SCORE_KEYS = ("overall", "findability", "metadata", "resources")

# Valid facet values — scores run 0-5; only values actually present in the
# data are rendered as items.
SCORE_VALUES = ["0", "1", "2", "3", "4", "5"]

# Numeric scores use COALESCE(..., -1) so missing scores sort below present
# ones; text columns sort case-insensitively.
REVIEWS_SORT = {
    "title": "LOWER(COALESCE(d.title, ''))",
    "org": "LOWER(COALESCE(d.org_display_name, ''))",
    "overall": "COALESCE(r.overall, -1)",
    "resources": "COALESCE(r.resources, -1)",
    "metadata": "COALESCE(r.metadata, -1)",
    "findability": "COALESCE(r.findability, -1)",
}

# The order /reviews starts in — shared by parse_sort and preserve_params.
REVIEWS_SORT_DEFAULT = ("overall", "asc")


def _score_clause(filters: dict, exclude: str | None, col: str) -> tuple[list, list]:
    """One score facet's WHERE clause + params: value → `col = %s`,
    `none` → `col IS NULL`. Skipped when the facet isn't selected or when
    `exclude` names it."""
    if exclude == col:
        return [], []
    v = filters.get(col)
    if v == "none":
        return [f"r.{col} IS NULL"], []
    if v:
        return [f"r.{col} = %s"], [int(v)]
    return [], []


# The four score clause builders, keyed by facet — the dict core.facet_where
# ANDs together (minus the excluded facet) for both the page list/count and
# the sidebar facet pools.
_SCORE_CLAUSES = {key: (lambda filters, exclude, col=key: _score_clause(filters, exclude, col)) for key in SCORE_KEYS}


def _facet_where(filters: dict, exclude: str | None = None) -> tuple[str, list]:
    """WHERE fragment + params for the score filters, omitting `exclude`
    (the facet group being counted). Routed through the shared
    core.facet_where helper with the four clause builders above."""
    return facet_where(_SCORE_CLAUSES, filters, exclude)


def reviews_stmts(filters: dict, sort: str, dir_: str) -> dict:
    """Return { count, list, params } for one (filters, sort, dir) combo.

    The dedup subquery joined to datasets supplies the current title/org.
    The ORDER BY appends title (ascending regardless of direction) then id,
    so tied rows keep a stable order.
    """
    where, params = _facet_where(filters)
    order_sql = order_by(REVIEWS_SORT, sort, dir_, "LOWER(COALESCE(d.title, '')), r.id")
    from_sql = f"({_DEDUP}) r JOIN datasets d ON d.id = r.dataset_id"

    return {
        "params": params,
        "count": Query(f"SELECT COUNT(*) AS n FROM {from_sql}{where}"),
        "list": Query(
            "SELECT r.dataset_id, d.title, d.org_slug, d.org_display_name,"
            "  r.overall, r.findability, r.metadata, r.resources"
            f" FROM {from_sql}{where}"
            f" ORDER BY {order_sql}"
            " LIMIT %s OFFSET %s",
        ),
    }


# --- /suggestions query builder ---
#
# No facets — count + list only, same builder shape as reviews_stmts. The
# dedup subquery carries the suggestion columns; the join to `datasets`
# supplies the *current* title/org/theme/tags.

# The dedup subquery for /suggestions — the latest ok review per dataset
# (as _DEDUP, but selecting the suggestion columns). "desc" is quoted: a
# reserved word.
_SUGGESTIONS_DEDUP = """
    SELECT DISTINCT ON (dataset_id) id, dataset_id, theme,
           theme_confidence, tags, title, "desc"
    FROM reviews WHERE ok = true ORDER BY dataset_id, id DESC
"""

# Text columns sort case-insensitively; confidence maps high/medium/low to
# 3/2/1 (so default asc lists the least confident first). `theme` sorts on
# the current theme (d.theme_primary), not the suggested one (r.theme).
SUGGESTIONS_SORT = {
    "title": "LOWER(COALESCE(d.title, ''))",
    "org": "LOWER(COALESCE(d.org_display_name, ''))",
    "theme": "LOWER(COALESCE(d.theme_primary, ''))",
    "confidence": "CASE r.theme_confidence WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END",
}

# The order /suggestions starts in — shared by parse_sort and pager_base.
SUGGESTIONS_SORT_DEFAULT = ("confidence", "asc")


def suggestions_stmts(sort: str, dir_: str) -> dict:
    """Return { count, list, params } for one (sort, dir) combo.

    As reviews_stmts: the dedup subquery joined to datasets, ordered by the
    sort expr with title then id appended, so tied rows keep a stable
    order.
    """
    order_sql = order_by(SUGGESTIONS_SORT, sort, dir_, "LOWER(COALESCE(d.title, '')), r.id")
    from_sql = f"({_SUGGESTIONS_DEDUP}) r JOIN datasets d ON d.id = r.dataset_id"

    return {
        "params": [],
        "count": Query(f"SELECT COUNT(*) AS n FROM {from_sql}"),
        "list": Query(
            "SELECT r.dataset_id, d.org_slug, d.org_display_name,"
            "  d.title, d.theme_primary AS current_theme, d.tags AS current_tags,"
            "  r.theme, r.theme_confidence, r.tags, r.title AS suggested_title,"
            '  r."desc" AS suggested_description'
            f" FROM {from_sql}"
            f" ORDER BY {order_sql}"
            " LIMIT %s OFFSET %s",
        ),
    }


# --- Sidebar facet counts (SQL aggregates over the same _facet_where) ---


def _facet_pool(filters: dict, key: str) -> Query:
    """Per-score count statement for one facet, its own selection excluded
    — the standard self-excluding sidebar pool. Missing scores group under
    '__none__'."""
    where, _ = _facet_where(filters, exclude=key)
    return Query(
        f"SELECT COALESCE(r.{key}::text, '__none__') AS value, COUNT(*) AS count"
        f" FROM ({_DEDUP}) r JOIN datasets d ON d.id = r.dataset_id{where}"
        f" GROUP BY COALESCE(r.{key}::text, '__none__')",
    )


@cached_unfiltered
def reviews_facet_counts(filters: dict) -> dict:
    """Sidebar facet counts for /reviews — every group counts over the pool
    filtered by the other groups. Returns { key: {value: count} } per score
    key, missing scores under '__none__'. The four pools run concurrently
    via core.fetch_parallel; no-filter calls return the memoised pools via
    core.cached_unfiltered.
    """
    pools = {key: _facet_pool(filters, key) for key in SCORE_KEYS}
    params = {key: _facet_where(filters, exclude=key)[1] for key in SCORE_KEYS}
    rows = fetch_parallel([lambda key=key: pools[key].all(*params[key]) for key in SCORE_KEYS])
    return {key: {r["value"]: r["count"] for r in rows[i]} for i, key in enumerate(SCORE_KEYS)}

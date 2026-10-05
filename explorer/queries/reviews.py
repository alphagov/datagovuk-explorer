"""Reviews helpers — DB-backed.

Reviews (quality scores) come from the ``reviews`` table (populated by
scripts/llm/ingest_reviews.py). Ingest is TRUNCATE + COPY — exactly one row
per CKAN guid — so no dedup is needed at query time. Join via datasets.ckan_id."""

import json
from functools import cache

from explorer.sort import order_by

from .core import Query, cached_unfiltered, facet_where, fetch_parallel

# ---------------------------------------------------------------------------
# Reviews — quality scores from the `reviews` table
# ---------------------------------------------------------------------------
# One row per dataset_ckan_id (enforced by UNIQUE constraint). json is TEXT,
# so it comes back as a plain string the views json.loads.

_LATEST_REVIEWS = Query("SELECT json FROM reviews ORDER BY dataset_ckan_id")

_REVIEW_FOR = Query("SELECT json FROM reviews WHERE dataset_ckan_id = %s")


@cache
def latest_reviews() -> list[dict]:
    """All reviews, one per dataset."""
    return [json.loads(row["json"]) for row in _LATEST_REVIEWS.all()]


def get_review(dataset_ckan_id: str) -> dict | None:
    """Review for one CKAN dataset guid, or None."""
    rows = _REVIEW_FOR.all(dataset_ckan_id)
    if not rows:
        return None
    return json.loads(rows[0]["json"])


# --- /reviews query builder ---
#
# Compiled per (filters, sort, dir). filters: { findability,
# resources } — a score value "0".."5" or "none" (missing
# score). Same pattern as datasets.py: the WHERE clauses drive the page
# list + count (filtering, sorting and pagination in the database instead
# of fetching + json.loads-ing every row in Python), and the sidebar facet
# counts use the same builder with their own group excluded — one clause
# builder, both consumers.

# Score dimensions — one facet group per dimension, mirroring the sortable
# columns. The denormalised subscore columns the ingest populates. A
# missing score is represented by the "none" facet.
SCORE_KEYS = ("findability", "resources")

FACET_KEYS = ("publisher", *SCORE_KEYS)

# Valid facet values — scores run 0-5; only values actually present in the
# data are rendered as items.
SCORE_VALUES = ["0", "1", "2", "3", "4", "5"]

# Numeric scores use COALESCE(..., -1) so missing scores sort below present
# ones; text columns sort case-insensitively.
REVIEWS_SORT = {
    "title": "LOWER(COALESCE(d.title, ''))",
    "org": "LOWER(COALESCE(d.org_display_name, ''))",
    "resources": "COALESCE(r.resources, -1)",
    "findability": "COALESCE(r.findability, -1)",
}

# The order /reviews starts in — shared by parse_sort and preserve_params.
REVIEWS_SORT_DEFAULT = ("findability", "asc")


def _publisher_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    """publisher (org slug) WHERE fragment + params, or ([], []) when
    skipped/excluded."""
    if exclude == "publisher":
        return [], []
    publisher = filters.get("publisher")
    if publisher:
        return ["d.org_slug = %s"], [publisher]
    return [], []


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


_PUBLISHER_NAME = "COALESCE(NULLIF(MAX(d.org_display_name), ''), d.org_slug)"

# The publisher + four score clause builders, keyed by facet — the dict
# core.facet_where ANDs together (minus the excluded facet) for both the
# page list/count and the sidebar facet pools.
_FACET_CLAUSES = {
    "publisher": _publisher_clause,
    **{key: (lambda filters, exclude, col=key: _score_clause(filters, exclude, col)) for key in SCORE_KEYS},
}


def _facet_where(filters: dict, exclude: str | None = None) -> tuple[str, list]:
    """WHERE fragment + params for the publisher + score filters, omitting
    `exclude` (the facet group being counted). Routed through the shared
    core.facet_where helper with the clause builders above."""
    return facet_where(_FACET_CLAUSES, filters, exclude)


def reviews_stmts(filters: dict, sort: str, dir_: str) -> dict:
    """Return { count, list, params } for one (filters, sort, dir) combo."""
    where, params = _facet_where(filters)
    order_sql = order_by(REVIEWS_SORT, sort, dir_, "LOWER(COALESCE(d.title, '')), r.dataset_ckan_id")
    from_sql = "reviews r JOIN datasets d ON d.ckan_id = r.dataset_ckan_id"

    return {
        "params": params,
        "count": Query(f"SELECT COUNT(*) AS n FROM {from_sql}{where}"),
        "list": Query(
            "SELECT d.ckan_id, d.title, d.org_slug, d.org_display_name,"
            "  r.findability, r.resources"
            f" FROM {from_sql}{where}"
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
        f" FROM reviews r JOIN datasets d ON d.ckan_id = r.dataset_ckan_id{where}"
        f" GROUP BY COALESCE(r.{key}::text, '__none__')",
    )


@cached_unfiltered
def reviews_facet_counts(filters: dict) -> dict:
    """Sidebar facet counts for /reviews — publisher + every score group
    counts over the pool filtered by the other groups. Returns
    { "publishers": [{value, name, count}], key: {value: count} } —
    publishers as an ordered list (count desc), score keys as dicts with
    missing scores under '__none__'. All pools run concurrently via
    core.fetch_parallel; no-filter calls return the memoised pools via
    core.cached_unfiltered.
    """
    pub_where, pub_params = _facet_where(filters, exclude="publisher")
    pub_q = Query(
        "SELECT d.org_slug AS value,"
        f"       {_PUBLISHER_NAME} AS name, COUNT(*) AS count"
        f" FROM reviews r JOIN datasets d ON d.ckan_id = r.dataset_ckan_id{pub_where}"
        " GROUP BY d.org_slug"
        f" ORDER BY count DESC, LOWER({_PUBLISHER_NAME})",
    )

    pools = {key: _facet_pool(filters, key) for key in SCORE_KEYS}
    params = {key: _facet_where(filters, exclude=key)[1] for key in SCORE_KEYS}
    results = fetch_parallel(
        [lambda: pub_q.all(*pub_params)] + [lambda key=key: pools[key].all(*params[key]) for key in SCORE_KEYS],
    )
    pub_rows = results[0]
    score_rows = results[1:]
    return {
        "publishers": pub_rows,
        **{key: {r["value"]: r["count"] for r in score_rows[i]} for i, key in enumerate(SCORE_KEYS)},
    }

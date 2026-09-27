"""Reviews / suggestions helpers — DB-backed, read from the `reviews`
table (populated by scripts/ingest_reviews.py from downloads/reviews/)."""

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

FACET_KEYS = ("publisher", *SCORE_KEYS)

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
# One facet: suggested theme (?theme=). The dedup subquery carries the
# suggestion columns; the join to `datasets` supplies the *current*
# title/org/theme/tags.

# The dedup subquery for /suggestions — the latest ok review per dataset
# (as _DEDUP, but selecting the suggestion columns). "desc" is quoted: a
# reserved word.
_SUGGESTIONS_DEDUP = """
    SELECT DISTINCT ON (dataset_id) id, dataset_id, theme,
           theme_confidence, tags, title, "desc"
    FROM reviews WHERE ok = true ORDER BY dataset_id, id DESC
"""

_SUGGESTIONS_FROM = f"({_SUGGESTIONS_DEDUP}) r JOIN datasets d ON d.id = r.dataset_id"

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

SUGGESTIONS_FACET_KEYS = ("theme", "tag")


def _suggestions_theme_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    if exclude == "theme":
        return [], []
    v = filters.get("theme")
    if v == "none":
        return ["r.theme IS NULL"], []
    if v:
        return ["r.theme = %s"], [v]
    return [], []


def _suggestions_tag_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    if exclude == "tag":
        return [], []
    v = filters.get("tag")
    if v == "none":
        return ["(r.tags IS NULL OR r.tags = '[]')"], []
    if v:
        return ["r.tags::jsonb ? %s"], [v]
    return [], []


_SUGGESTIONS_CLAUSES = {"theme": _suggestions_theme_clause, "tag": _suggestions_tag_clause}


def _suggestions_facet_where(filters: dict, exclude: str | None = None) -> tuple[str, list]:
    return facet_where(_SUGGESTIONS_CLAUSES, filters, exclude)


def suggestions_stmts(filters: dict, sort: str, dir_: str) -> dict:
    """Return { count, list, params } for one (filters, sort, dir) combo."""
    where, params = _suggestions_facet_where(filters)
    order_sql = order_by(SUGGESTIONS_SORT, sort, dir_, "LOWER(COALESCE(d.title, '')), r.id")

    return {
        "params": params,
        "count": Query(f"SELECT COUNT(*) AS n FROM {_SUGGESTIONS_FROM}{where}"),
        "list": Query(
            "SELECT r.dataset_id, d.org_slug, d.org_display_name,"
            "  d.title, d.theme_primary AS current_theme, d.tags AS current_tags,"
            "  r.theme, r.theme_confidence, r.tags, r.title AS suggested_title,"
            '  r."desc" AS suggested_description'
            f" FROM {_SUGGESTIONS_FROM}{where}"
            f" ORDER BY {order_sql}"
            " LIMIT %s OFFSET %s",
        ),
    }


@cached_unfiltered
def suggestions_facet_counts(filters: dict) -> dict:
    """Sidebar facet counts for /suggestions — suggested theme and tag."""
    theme_where, theme_params = _suggestions_facet_where(filters, exclude="theme")
    theme_q = Query(
        "SELECT COALESCE(r.theme, '__none__') AS value, COUNT(*) AS count"
        f" FROM {_SUGGESTIONS_FROM}{theme_where}"
        " GROUP BY COALESCE(r.theme, '__none__')",
    )

    tag_where, tag_params = _suggestions_facet_where(filters, exclude="tag")
    has_tags_cond = "r.tags IS NOT NULL AND r.tags != '[]'"
    no_tags_cond = "(r.tags IS NULL OR r.tags = '[]')"
    if tag_where:
        tag_filter = f"{tag_where} AND {has_tags_cond}"
        tag_none_filter = f"{tag_where} AND {no_tags_cond}"
    else:
        tag_filter = f" WHERE {has_tags_cond}"
        tag_none_filter = f" WHERE {no_tags_cond}"
    tag_from = f"{_SUGGESTIONS_FROM}, jsonb_array_elements_text(r.tags::jsonb) AS t(value)"
    tag_q = Query(
        f"SELECT t.value, COUNT(*) AS count FROM {tag_from}{tag_filter} GROUP BY t.value HAVING COUNT(*) > 10",
    )
    tag_none_q = Query(
        f"SELECT COUNT(*) AS count FROM {_SUGGESTIONS_FROM}{tag_none_filter}",
    )

    theme_rows, tag_rows, tag_none_rows = fetch_parallel(
        [
            lambda: theme_q.all(*theme_params),
            lambda: tag_q.all(*tag_params),
            lambda: tag_none_q.all(*tag_params),
        ]
    )

    tag_counts = {r["value"]: r["count"] for r in tag_rows}
    none_count = tag_none_rows[0]["count"] if tag_none_rows else 0
    if none_count:
        tag_counts["__none__"] = none_count

    return {
        "theme": {r["value"]: r["count"] for r in theme_rows},
        "tag": tag_counts,
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
        f" FROM ({_DEDUP}) r JOIN datasets d ON d.id = r.dataset_id{pub_where}"
        " GROUP BY d.org_slug"
        f" ORDER BY count DESC, LOWER({_PUBLISHER_NAME})",
    )

    pools = {key: _facet_pool(filters, key) for key in SCORE_KEYS}
    params = {key: _facet_where(filters, exclude=key)[1] for key in SCORE_KEYS}
    results = fetch_parallel(
        [lambda: pub_q.all(*pub_params)]
        + [lambda key=key: pools[key].all(*params[key]) for key in SCORE_KEYS],
    )
    pub_rows = results[0]
    score_rows = results[1:]
    return {
        "publishers": pub_rows,
        **{key: {r["value"]: r["count"] for r in score_rows[i]} for i, key in enumerate(SCORE_KEYS)},
    }

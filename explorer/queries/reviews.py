"""Reviews / suggestions helpers — DB-backed, read from the `reviews`
table (populated by scripts/ingest_reviews.py from the JSONL)."""

import json

from .core import Query, cached_unfiltered, facet_where, fetch_parallel

# ---------------------------------------------------------------------------
# Reviews / suggestions — DB-backed, read from the `reviews` table
# ---------------------------------------------------------------------------
#
# The reviews table stores one row per JSONL record with the full record in
# `json`. Only ok:true records count, and only the latest one per
# dataset_id — latest = later row in the file = higher `id` (ingest inserts
# in file order). `json` is TEXT, so it comes back as a plain string and
# the views keep their json.loads + dict access.

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

# The dedup subquery every statement below is built on: one (latest) ok
# review per dataset — DISTINCT ON keeps the highest-id (latest) record
# per dataset_id. The join to `datasets` supplies the *current* title/org
# rather than review-time values from the JSON (docs/pagination-plan.md
# decision 2 — consistent with every other page; the review-time JSON is
# still preserved in `reviews.json` for the dataset detail page).
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

# Sortable column key → SQL ORDER BY expression. Numeric scores use
# COALESCE(..., -1) so missing scores sort below present ones (the old
# _score_or_minus_one); text columns LOWER() case-insensitively.
REVIEWS_SORT_EXPRS = {
    "title": "LOWER(COALESCE(d.title, ''))",
    "org": "LOWER(COALESCE(d.org_display_name, ''))",
    "overall": "COALESCE(r.overall, -1)",
    "resources": "COALESCE(r.resources, -1)",
    "metadata": "COALESCE(r.metadata, -1)",
    "findability": "COALESCE(r.findability, -1)",
}


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

    The list query fetches only the page's rows: the dedup subquery joined
    to datasets for the current title/org, filtered by the score facets,
    ordered by the sort expr + an unconditional title-ascending tiebreak
    (the two-pass stable sort's "ties break title-asc regardless of dir"
    — `, LOWER(COALESCE(d.title,''))` appended to every ORDER BY) + `,
    r.id` pinning ties on (sort key, title) to ingest order (the stable
    pre-order of latest_reviews()); without the pin an unpinned ORDER BY
    would reshuffle pages whenever rows tie.
    """
    where, params = _facet_where(filters)
    order_sql = f"{REVIEWS_SORT_EXPRS[sort]} {'DESC' if dir_ == 'desc' else 'ASC'}, LOWER(COALESCE(d.title, '')), r.id"
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
# dedup subquery carries the suggestion columns (suggested theme, suggested
# tags as JSON text, suggested title, suggested description, confidence);
# the join to `datasets` supplies the *current* title/org/theme/tags rather
# than review-time values from the JSON (docs/pagination-plan.md decision 2).

# The dedup subquery for /suggestions — one (latest) ok review per dataset,
# same DISTINCT ON as _DEDUP but selecting the suggestion columns. `"desc"`
# is quoted: desc is a reserved word.
_SUGGESTIONS_DEDUP = """
    SELECT DISTINCT ON (dataset_id) id, dataset_id, theme,
           theme_confidence, tags, title, "desc"
    FROM reviews WHERE ok = true ORDER BY dataset_id, id DESC
"""

# Sortable column key → SQL ORDER BY expression. Text columns LOWER()
# case-insensitively; confidence maps high/medium/low to 3/2/1 (default asc
# = ambiguous first, unchanged). `theme` sorts on the *current* theme
# (d.theme_primary), mirroring the old Python sort key, not the suggested
# one (r.theme).
SUGGESTIONS_SORT_EXPRS = {
    "title": "LOWER(COALESCE(d.title, ''))",
    "org": "LOWER(COALESCE(d.org_display_name, ''))",
    "theme": "LOWER(COALESCE(d.theme_primary, ''))",
    "confidence": "CASE r.theme_confidence WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END",
}


def suggestions_stmts(sort: str, dir_: str) -> dict:
    """Return { count, list, params } for one (sort, dir) combo.

    The list query fetches only the page's rows: the dedup subquery joined
    to datasets for the current title/org/theme/tags, ordered by the sort
    expr + an unconditional title-ascending tiebreak (the two-pass stable
    sort's "ties break title-asc regardless of dir" — `,
    LOWER(COALESCE(d.title,''))` appended to every ORDER BY) + `, r.id`
    pinning ties on (sort key, title) to ingest order (the stable pre-order
    of latest_reviews()); without the pin an unpinned ORDER BY would
    reshuffle pages whenever rows tie.
    """
    order_sql = (
        f"{SUGGESTIONS_SORT_EXPRS[sort]} {'DESC' if dir_ == 'desc' else 'ASC'},"
        " LOWER(COALESCE(d.title, '')), r.id"
    )
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
    — the standard self-excluding sidebar: each group counts over the pool
    filtered by every *other* active facet. Missing scores group under
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
    filtered by the other groups. Returns { key: {value: count} } for each
    score key, missing scores under the '__none__' value.

    The four pools are four independent single-SELECT aggregates, so they
    run concurrently via core.fetch_parallel. No-filter calls (the common
    view) return the memoised pools via core.cached_unfiltered.
    """
    pools = {key: _facet_pool(filters, key) for key in SCORE_KEYS}
    params = {key: _facet_where(filters, exclude=key)[1] for key in SCORE_KEYS}
    rows = fetch_parallel([lambda key=key: pools[key].all(*params[key]) for key in SCORE_KEYS])
    return {key: {r["value"]: r["count"] for r in rows[i]} for i, key in enumerate(SCORE_KEYS)}

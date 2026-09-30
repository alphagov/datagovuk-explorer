"""Suggestions helpers — DB-backed.

Suggestions (theme/tags/title/desc) come from the ``suggestions`` table
(populated by scripts/llm/ingest_suggestions.py). Ingest is TRUNCATE + COPY —
exactly one row per dataset_id — so no dedup is needed at query time."""

import json

from explorer.sort import order_by

from .core import Query, cached_unfiltered, facet_where, fetch_parallel

# --- Single-record lookup ---

_SUGGESTION_FOR = Query("SELECT json FROM suggestions WHERE dataset_id = %s")


def get_classification(dataset_id: str) -> dict | None:
    """Latest ok suggestion for one dataset id, or None."""
    rows = _SUGGESTION_FOR.all(dataset_id)
    if not rows:
        return None
    raw = json.loads(rows[0]["json"])
    return {
        **raw,
        "theme": raw.get("suggested_theme"),
        "theme_confidence": raw.get("suggested_theme_confidence"),
        "tags": raw.get("suggested_tags") or [],
    }


# --- /suggestions query builder ---
#
# One facet: suggested theme (?theme=). The join to `datasets` supplies
# the *current* title/org/theme/tags.

_SUGGESTIONS_FROM = "suggestions r JOIN datasets d ON d.id = r.dataset_id"

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
    order_sql = order_by(SUGGESTIONS_SORT, sort, dir_, "LOWER(COALESCE(d.title, '')), r.dataset_id")

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
        ],
    )

    tag_counts = {r["value"]: r["count"] for r in tag_rows}
    none_count = tag_none_rows[0]["count"] if tag_none_rows else 0
    if none_count:
        tag_counts["__none__"] = none_count

    return {
        "theme": {r["value"]: r["count"] for r in theme_rows},
        "tag": tag_counts,
    }

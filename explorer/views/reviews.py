"""GET /reviews — list of LLM-reviewed datasets, read from the reviews
    table (populated by scripts/ingest_reviews.py from the JSONL). Sorted
    worst-first by default so quality problems surface first; every column
    is sortable via ?sort=&dir=, and the sidebar facets filter by each
    score group (?overall=, ?findability=, ?metadata=, ?resources=).

The page list, count, sort and facet counts all run in SQL (the shared
reviews_stmts/reviews_facet_counts builders in explorer/queries/reviews.py
— the /datasets pattern), so only the page's rows are fetched, not the
whole reviews table. Title/org come from the current datasets row via the
join, not review-time values from the JSON (docs/pagination-plan.md
decision 2).
"""

from django.shortcuts import render

from explorer import facets
from explorer.queries.reviews import (
    REVIEWS_SORT_EXPRS,
    SCORE_KEYS,
    SCORE_VALUES,
    reviews_facet_counts,
    reviews_stmts,
)

from .core import _sort_dir, paginate

# Score dimensions in sidebar order — the facet-group labels for the four
# pools computed in SQL (queries/reviews.py owns the keys/clauses).
SCORE_GROUPS = [
    {"key": "overall", "label": "Overall"},
    {"key": "findability", "label": "Findability"},
    {"key": "metadata", "label": "Metadata"},
    {"key": "resources", "label": "Resources"},
]


def _score_facet_group(key: str, label: str, counts: dict, current: str | None) -> dict | None:
    """One score facet group from the SQL pool counts — the values present
    in the data, scaled proportion bars, plus the "No score" trailing
    bucket when any review in the pool is missing that score. None when
    the pool is empty."""
    no_score = counts.pop("__none__", 0)
    pool = counts  # values only, __none__ removed above
    trailing = None
    if no_score:
        pool_max = max([*pool.values(), no_score, 1])
        trailing = [
            {
                "value": "none",
                "name": "No score",
                "count": no_score,
                "active": current == "none",
                "proportion": no_score / pool_max,
            },
        ]
    return facets.facet_counts_group(
        key,
        label,
        f"Filter by {label.lower()} score",
        [(v, f"{v}/5") for v in SCORE_VALUES],
        pool,
        current,
        proportions=True,
        trailing=trailing,
    )


def reviews(request):
    """GET /reviews — the LLM review table with per-score facets."""
    # Current facet selections — single-select per group, combinable across
    # groups. A value must be a valid score or "none" to be accepted.
    filters: dict[str, str] = {}
    for key in SCORE_KEYS:
        v = request.GET.get(key)
        if v == "none" or v in SCORE_VALUES:
            filters[key] = v

    sort, dir_ = _sort_dir(request, REVIEWS_SORT_EXPRS, "overall")

    # Shared query-string machinery from explorer/facets.py: the base keeps
    # sort/dir then the active facets in SCORE_KEYS order; facet_qs drops
    # sort/dir for the sort/pagination links; facet_url sets or clears one
    # facet value (empty value clears it, back to the pills).
    base_params = facets.preserve_params(sort, dir_, list(filters.items()))
    facet_url = facets.facet_url_for(base_params)
    facet_qs = facets.facet_qs(base_params, include_sort=False)
    pager_base = facets.pager_base(base_params)

    # Reviews matching all active filters — count + page in SQL (only the
    # page's rows are fetched).
    stmts = reviews_stmts(filters, sort, dir_)
    shown_count = stmts["count"].get(*stmts["params"])["n"]

    pagination = paginate(request, shown_count)
    page_reviews = stmts["list"].all(*stmts["params"], pagination["page_size"], pagination["offset"])

    # Sidebar facet groups — each score group counts over the pool filtered
    # by every other group (the standard self-excluding sidebar).
    facet_counts = reviews_facet_counts(filters)
    facet_groups = []
    for g in SCORE_GROUPS:
        group = _score_facet_group(g["key"], g["label"], facet_counts[g["key"]], filters.get(g["key"]))
        if group is not None:
            facet_groups.append(group)

    return render(
        request,
        "reviews.html",
        {
            "title": f"Dataset reviews ({shown_count})",
            "section": "reviews",
            "reviews": page_reviews,
            "total": shown_count,
            "shown": shown_count,
            **pagination,
            "sort": sort,
            "dir": dir_,
            "facet_groups": facet_groups,
            "filters": filters,
            "facet_qs": facet_qs,
            "facet_url": facet_url,
            "pager_base": pager_base,
        },
    )

"""GET /suggestions — list of LLM-classified datasets with theme/tag/title
suggestions, read from the reviews table (populated by
scripts/ingest_reviews.py). Sorted by confidence so low-confidence
(ambiguous) datasets surface first. Only the latest classification per
dataset is shown.

The page list, count and sort all run in SQL (the shared
suggestions_stmts builder in explorer/queries/reviews.py — the /datasets
pattern), so only the page's rows are fetched, not the whole reviews
table. Title/org/theme/tags come from the current datasets row via the
join, not review-time values from the JSON (docs/pagination-plan.md
decision 2); the suggested theme/tags/title/description come from the
review row (reviews.title is the *suggested* title — the naming gotcha).
"""

import json

from django.shortcuts import render

from explorer import facets
from explorer.queries.reviews import SUGGESTIONS_SORT_EXPRS, suggestions_stmts

from .core import _sort_dir, paginate


def suggestions(request):
    """GET /suggestions — the LLM classification table with suggested themes."""
    sort, dir_param = _sort_dir(request, SUGGESTIONS_SORT_EXPRS, "confidence")

    # Count + page in SQL (only the page's rows are fetched).
    stmts = suggestions_stmts(sort, dir_param)
    total = stmts["count"].get()["n"]

    pagination = paginate(request, total)
    rows = stmts["list"].all(pagination["page_size"], pagination["offset"])

    # Per-page-row decoration: r.tags is the suggested tags as JSON text
    # (ingest json.dumps the list) — decode per row, it's a small list.
    # theme_changed is a display flag computed on the fetched row, not a
    # filter (the suggested theme compared against the current one).
    suggestion_rows = [
        {
            **r,
            "tags": json.loads(r["tags"]) if r["tags"] else [],
            "theme_changed": r["theme"] != r["current_theme"],
        }
        for r in rows
    ]

    pager_base = facets.pager_base({"sort": sort, "dir": dir_param})

    return render(
        request,
        "suggestions.html",
        {
            "title": f"Suggestions ({total})",
            "section": "datasets",
            "suggestions": suggestion_rows,
            "total": total,
            "shown": total,
            # Two-pane frame with a blank facets sidebar so Suggestions lines
            # up with the other Datasets-group pages (see _app_layout.html).
            "show_facet_pane": True,
            "pager_base": pager_base,
            **pagination,
            "sort": sort,
            "dir": dir_param,
        },
    )

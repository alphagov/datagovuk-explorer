"""GET /suggestions — list of LLM-classified datasets with theme/tag/title
suggestions, read from the reviews table (populated by
scripts/ingest_reviews.py). Sorted by confidence so low-confidence
(ambiguous) datasets surface first. Only the latest classification per
dataset is shown.

The page list, count and sort all run in SQL (the shared
suggestions_stmts builder in explorer/queries/reviews.py — the /datasets
pattern), so only the page's rows are fetched, not the whole reviews
table. Title/org/theme/tags come from the current datasets row via the
join, not review-time values from the JSON; the suggested theme/tags/title/
description come from the review row (reviews.title is the *suggested*
title — the naming gotcha).
"""

import json

from django.shortcuts import render

from explorer import facets
from explorer.queries.reviews import SUGGESTIONS_SORT, suggestions_stmts
from explorer.sort import parse_sort

from .core import paginate


def suggestions(request):
    """GET /suggestions — the LLM classification table with suggested themes."""
    sort, dir_ = parse_sort(request, SUGGESTIONS_SORT, "confidence")

    # Count + page in SQL (only the page's rows are fetched).
    stmts = suggestions_stmts(sort, dir_)
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

    pager_base = facets.pager_base({"sort": sort, "dir": dir_})

    return render(
        request,
        "suggestions.html",
        {
            "title": f"Suggestions ({total})",
            "section": "datasets",
            "suggestions": suggestion_rows,
            "total": total,
            "shown": total,
            "pager_base": pager_base,
            **pagination,
            "sort": sort,
            "dir": dir_,
        },
    )

"""GET /suggestions — list of LLM-classified datasets with theme/tag/title
suggestions, read from the suggestions table (populated by
scripts/ingest_suggestions.py from downloads/suggestions/). Sorted by
confidence so low-confidence (ambiguous) datasets surface first. Only the
latest classification per dataset is shown.

The page list, count and sort all run in SQL (the shared
suggestions_stmts builder in explorer/queries/reviews.py — the /datasets
pattern), so only the page's rows are fetched, not the whole suggestions
table. Title/org/theme/tags come from the current datasets row via the
join, not suggestion-time values from the JSON; the suggested theme/tags/
title/description come from the suggestion row.

Sidebar facet: suggested theme (?theme=<slug>).
"""

import json

from django.shortcuts import render

from explorer import facets
from explorer.helpers import theme_label
from explorer.queries.reviews import (
    SUGGESTIONS_SORT,
    SUGGESTIONS_SORT_DEFAULT,
    suggestions_facet_counts,
    suggestions_stmts,
)
from explorer.sort import parse_sort

from .core import paginate, pill


def suggestions(request):
    """GET /suggestions — the LLM classification table with suggested themes."""
    # Facet selections.
    filters: dict[str, str] = {}
    theme_val = request.GET.get("theme")
    if theme_val == "none" or (theme_val and theme_val.strip()):
        filters["theme"] = theme_val
    tag_val = request.GET.get("tag")
    if tag_val == "none" or (tag_val and tag_val.strip()):
        filters["tag"] = tag_val

    sort, dir_ = parse_sort(request, SUGGESTIONS_SORT, *SUGGESTIONS_SORT_DEFAULT)

    base_params = facets.preserve_params(sort, dir_, list(filters.items()), defaults=SUGGESTIONS_SORT_DEFAULT)
    facet_url = facets.facet_url_for(base_params)
    facet_qs = facets.facet_qs(base_params, include_sort=False)
    pager_base = facets.pager_base(base_params)

    # Count + page in SQL (only the page's rows are fetched).
    stmts = suggestions_stmts(filters, sort, dir_)
    total = stmts["count"].get(*stmts["params"])["n"]

    pagination = paginate(request, total)
    rows = stmts["list"].all(*stmts["params"], pagination["page_size"], pagination["offset"])

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

    # Sidebar: suggested-theme and suggested-tag facets.
    counts = suggestions_facet_counts(filters)

    # Theme facet.
    theme_counts = dict(counts["theme"])
    no_theme = theme_counts.pop("__none__", 0)
    theme_trailing = None
    if no_theme:
        pool_max = max([*theme_counts.values(), no_theme, 1])
        theme_trailing = [
            {
                "value": "none",
                "name": "No theme",
                "count": no_theme,
                "active": filters.get("theme") == "none",
                "proportion": no_theme / pool_max,
            },
        ]
    master = sorted(theme_counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    theme_group = facets.facet_counts_group(
        "theme",
        "Suggested theme",
        "Filter by suggested theme",
        [(slug, theme_label(slug)) for slug, _ in master],
        theme_counts,
        filters.get("theme"),
        proportions=True,
        trailing=theme_trailing,
        plural="themes",
        toggle_base=base_params,
        expanded=request.GET.get("themes") == "all",
    )

    # Tag facet.
    tag_counts = dict(counts["tag"])
    no_tags = tag_counts.pop("__none__", 0)
    tag_trailing = None
    if no_tags:
        pool_max = max([*tag_counts.values(), no_tags, 1])
        tag_trailing = [
            {
                "value": "none",
                "name": "No tags",
                "count": no_tags,
                "active": filters.get("tag") == "none",
                "proportion": no_tags / pool_max,
            },
        ]
    tag_master = sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    tag_group = facets.facet_counts_group(
        "tag",
        "Suggested tag",
        "Filter by suggested tag",
        [(tag, tag) for tag, _ in tag_master],
        tag_counts,
        filters.get("tag"),
        proportions=True,
        trailing=tag_trailing,
        plural="tags",
        toggle_base=base_params,
        expanded=request.GET.get("tags") == "all",
    )

    facet_groups = {}
    if theme_group is not None:
        facet_groups[theme_group["key"]] = theme_group
    if tag_group is not None:
        facet_groups[tag_group["key"]] = tag_group

    pills = []
    if filters.get("theme"):
        v = filters["theme"]
        label = "No theme" if v == "none" else theme_label(v)
        pills.append(pill("Suggested theme", label, facet_url("theme", "")))
    if filters.get("tag"):
        v = filters["tag"]
        label = "No tags" if v == "none" else v
        pills.append(pill("Suggested tag", label, facet_url("tag", "")))

    return render(
        request,
        "suggestions.html",
        {
            "title": f"Suggestions ({total})",
            "nav_key": "suggestions",
            "suggestions": suggestion_rows,
            "total": total,
            "shown": total,
            "pager_base": pager_base,
            **pagination,
            "sort": sort,
            "dir": dir_,
            "facet_groups": facet_groups,
            "pills": pills,
            "facet_qs": facet_qs,
            "facet_url": facet_url,
        },
    )

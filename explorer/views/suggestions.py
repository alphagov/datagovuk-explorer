"""GET /suggestions — list of LLM-classified datasets with theme/tag/title
suggestions, read from the suggestions table (populated by
scripts/llm/ingest_suggestions.py from downloads/suggestions/). Sorted by
confidence so low-confidence (ambiguous) datasets surface first. Only the
latest classification per dataset is shown.

GET /suggestions/download.csv — the same filtered, sorted rows unpaginated,
with the current and suggested value of each field split into its own
column (see _SUGGESTIONS_CSV_COLUMNS).

The page list, count and sort all run in SQL (the shared
suggestions_stmts builder in explorer/queries/suggestions.py — the /datasets
pattern), so only the page's rows are fetched, not the whole suggestions
table. Title/org/theme/tags come from the current datasets row via the
join, not suggestion-time values from the JSON; the suggested theme/tags/
title/description come from the suggestion row.

Sidebar facet: suggested theme (?theme=<slug>).
"""

import json

from django.shortcuts import render

from explorer import facets
from explorer.csv_export import csv_filename, csv_response
from explorer.helpers import theme_label
from explorer.queries.core import iter_rows
from explorer.queries.suggestions import (
    SUGGESTIONS_SORT,
    SUGGESTIONS_SORT_DEFAULT,
    suggestions_facet_counts,
    suggestions_stmts,
)
from explorer.sort import parse_sort

from .core import paginate, pill


def _listing(request) -> dict:
    """Resolve one /suggestions request into its filters, sort state and
    compiled count+list statements — shared by the page and the CSV download
    so the exported rows can't drift from the table."""
    # Facet selections.
    filters: dict[str, str] = {}
    theme_val = request.GET.get("theme")
    if theme_val == "none" or (theme_val and theme_val.strip()):
        filters["theme"] = theme_val
    tag_val = request.GET.get("tag")
    if tag_val == "none" or (tag_val and tag_val.strip()):
        filters["tag"] = tag_val

    sort, dir_ = parse_sort(request, SUGGESTIONS_SORT, *SUGGESTIONS_SORT_DEFAULT)
    stmts = suggestions_stmts(filters, sort, dir_)
    return {
        "filters": filters,
        "sort": sort,
        "dir": dir_,
        "stmts": stmts,
        "total": stmts["count"].get(*stmts["params"])["n"],
    }


# CSV export columns — the table's own fields with the current and suggested
# value of each split out (the description is deliberately omitted: it is too
# long for a spreadsheet cell), then the dataset GUID last.
_SUGGESTIONS_CSV_COLUMNS = [
    ("Current title", "title"),
    ("Suggested title", "suggested_title"),
    ("Publisher", "org_display_name"),
    ("Current theme", "current_theme"),
    ("Suggested theme", "theme"),
    ("Current tags", "current_tags"),
    ("Suggested tags", "tags"),
    ("Confidence", "theme_confidence"),
    ("Dataset ID", "ckan_id"),
]


def _csv_row(r: dict) -> dict:
    """One SQL row → export shape. Both tag columns normalise to a
    semicolon-separated list: current tags are a space-joined string on the
    datasets row, suggested tags a JSON array on the suggestion row."""
    return {
        **r,
        "current_tags": "; ".join((r["current_tags"] or "").split()),
        "tags": "; ".join(json.loads(r["tags"]) if r["tags"] else []),
    }


def suggestions(request):
    """GET /suggestions — the LLM classification table with suggested themes."""
    listing = _listing(request)
    filters = listing["filters"]
    sort, dir_ = listing["sort"], listing["dir"]

    base_params = facets.preserve_params(sort, dir_, list(filters.items()), defaults=SUGGESTIONS_SORT_DEFAULT)
    facet_url = facets.facet_url_for(base_params)
    facet_qs = facets.facet_qs(base_params, include_sort=False)
    pager_base = facets.pager_base(base_params)

    # Count + page in SQL (only the page's rows are fetched).
    stmts = listing["stmts"]
    total = listing["total"]

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
            "download_url": f"/suggestions/download.csv{pager_base}",
        },
    )


def suggestions_download(request):
    """GET /suggestions/download.csv — the same filtered, sorted suggestions
    as the table, unpaginated and as a CSV attachment."""
    listing = _listing(request)
    rows = (_csv_row(r) for r in iter_rows(listing["stmts"]))
    return csv_response(csv_filename("suggestions", listing["filters"]), _SUGGESTIONS_CSV_COLUMNS, rows)

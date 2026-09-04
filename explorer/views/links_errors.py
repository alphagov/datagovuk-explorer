"""GET /links/errors — the Link errors sub-report under Links.

Reads the `link_errors` table (ingested by scripts/ingest_link_errors.py
from data/errors-current.csv): every checked resource link across all
datasets — both check runs, and the OK/2xx rows that previously failed and
are now resolved (shown, styled positively, not filtered out). Sortable via
?sort= & ?dir=, filterable by outcome/category, HTTP status (with the
"No response" bucket for the code-less DNS/timeout rows), harvest state
(Harvested/Manual/Unknown) and publisher via the single-select sidebar
facets, paginated (100/page). Default sort is most-recent check first.

The harvest state rides the datasets LEFT JOIN (queries/link_errors.py):
harvested/manual from the snapshot, unknown when the package is absent
from it (docs/link-errors-report.md §3 — derived, never stored).

Sits under the top-level Links nav item (section = "links", shared sub-nav
with /links).
"""

from django.shortcuts import render

from explorer import facets
from explorer.queries.link_errors import (
    CATEGORY_LABELS,
    HARVEST_STATES,
    LINK_ERRORS_SORT_COLUMNS,
    TO_DELETE_VALUES,
    link_errors_facet_counts,
    link_errors_stats,
    link_errors_stmts,
)

from .core import _sort_dir, paginate

# Facet-group labels (sidebar order — to delete, outcome/category, HTTP
# status, harvest state, publisher).
HARVEST_LABELS = dict(HARVEST_STATES)
TO_DELETE_LABELS = dict(TO_DELETE_VALUES)


def _category_name(value: str) -> str:
    """Display name for a raw category code (facet items and pills)."""
    return CATEGORY_LABELS.get(value, (value or "").title())


def link_errors(request):
    """GET /links/errors — the link-check report with sidebar facets."""
    stats = link_errors_stats()

    # Filter-independent master pools (the validation whitelists and the
    # sidebar item order) — the no-filter facet counts, memoised.
    base_pool = link_errors_facet_counts({})
    category_master = [(c["value"], _category_name(c["value"])) for c in base_pool["categories"]]
    status_master = [(s["value"], s["value"]) for s in base_pool["statuses"]]
    publisher_master = [(p["value"], p["value"]) for p in base_pool["publishers"]]
    valid_categories = {value for value, _ in category_master}
    valid_statuses = {value for value, _ in status_master}
    valid_publishers = {value for value, _ in publisher_master}

    # Current facet selections — single-select per group, combinable across
    # groups; unknown values fall back to no selection.
    category = request.GET.get("category")
    current_category = category if category in valid_categories else None

    status = request.GET.get("status")
    current_status = status if status == "__none__" or status in valid_statuses else None

    to_delete = request.GET.get("to_delete")
    current_to_delete = to_delete if to_delete in TO_DELETE_LABELS else None

    harvested = request.GET.get("harvested")
    current_harvested = harvested if harvested in HARVEST_LABELS else None

    publisher = request.GET.get("publisher")
    current_publisher = publisher if publisher in valid_publishers else None

    filters = {
        "category": current_category,
        "status": current_status,
        "to_delete": current_to_delete,
        "harvested": current_harvested,
        "publisher": current_publisher,
    }

    sort, dir_ = _sort_dir(request, LINK_ERRORS_SORT_COLUMNS, "checked", "desc")

    # Count + page in SQL — only the page's rows are fetched (the LEFT
    # JOIN supplies org slug / harvest state / harvest source per row).
    stmts_out = link_errors_stmts(filters, sort, dir_)
    shown_count = stmts_out["count"].get(*stmts_out["params"])["n"]

    pagination = paginate(request, shown_count)
    page_rows = stmts_out["list"].all(*stmts_out["params"], pagination["page_size"], pagination["offset"])

    # Shared query-string machinery — ordered base (sort, dir, then each
    # active facet in a fixed order); facet_qs drops sort/dir for the
    # sort_link/pagination macros; facet_url sets/clears one facet value.
    base_params = facets.preserve_params(
        sort,
        dir_,
        [
            ("category", current_category),
            ("status", current_status),
            ("to_delete", current_to_delete),
            ("harvested", current_harvested),
            ("publisher", current_publisher),
        ],
    )
    facet_url = facets.facet_url_for(base_params)
    facet_qs = facets.facet_qs(base_params, include_sort=False)
    pager_base = facets.pager_base(base_params)

    # Sidebar facet groups — each group counts over the pool filtered by
    # every other group (the standard self-excluding sidebar). To delete
    # sits at the top: the checker's remove-from-catalogue recommendation
    # is the first thing a user decides before drilling into why.
    pool = link_errors_facet_counts(filters)
    facet_groups = [
        group
        for group in (
            facets.facet_counts_group(
                "to_delete",
                "To delete",
                "Filter by the remove-link recommendation",
                TO_DELETE_VALUES,
                pool["to_delete"],
                current_to_delete,
                proportions=True,
            ),
            facets.facet_counts_group(
                "category",
                "Outcome",
                "Filter by outcome",
                category_master,
                {c["value"]: c["count"] for c in pool["categories"]},
                current_category,
                proportions=True,
            ),
            facets.facet_counts_group(
                "status",
                "HTTP status",
                "Filter by HTTP status",
                status_master,
                {s["value"]: s["count"] for s in pool["statuses"]},
                current_status,
                proportions=True,
                trailing=(
                    [
                        {
                            "value": "__none__",
                            "name": "No response",
                            "count": pool["no_response"],
                            "active": current_status == "__none__",
                        },
                    ]
                    if pool["no_response"]
                    else None
                ),
            ),
            facets.facet_counts_group(
                "harvested",
                "Harvested",
                "Filter by harvest status",
                HARVEST_STATES,
                pool["harvested"],
                current_harvested,
                proportions=True,
            ),
            facets.facet_counts_group(
                "publisher",
                "Publisher",
                "Filter by publisher",
                publisher_master,
                {p["value"]: p["count"] for p in pool["publishers"]},
                current_publisher,
                proportions=True,
            ),
        )
        if group is not None
    ]

    # Decorate only the page's rows: the status cell text (code + category
    # name, or the category name alone for the code-less DNS/timeout rows).
    for r in page_rows:
        label = _category_name(r["category"])
        r["category_label"] = label
        r["ok"] = r["category"] == "OK"
        r["status_text"] = f"{r['status']} {label}" if r["status"] is not None else label

    # Pill labels for the active-filter strip (header left) — same order
    # as the sidebar facets (to delete, outcome, status, harvested,
    # publisher).
    pills = [
        {
            "label": "To delete",
            "value": TO_DELETE_LABELS[current_to_delete],
            "href": facet_url("to_delete", ""),
            "aria": "Remove to delete filter: " + TO_DELETE_LABELS[current_to_delete],
        }
        if current_to_delete
        else None,
        {
            "label": "Outcome",
            "value": _category_name(current_category),
            "href": facet_url("category", ""),
            "aria": "Remove outcome filter: " + _category_name(current_category),
        }
        if current_category
        else None,
        {
            "label": "Status",
            "value": "No response" if current_status == "__none__" else current_status,
            "href": facet_url("status", ""),
            "aria": "Remove status filter: " + ("No response" if current_status == "__none__" else current_status),
        }
        if current_status
        else None,
        {
            "label": "Harvested",
            "value": HARVEST_LABELS[current_harvested],
            "href": facet_url("harvested", ""),
            "aria": "Remove harvested filter: " + HARVEST_LABELS[current_harvested],
        }
        if current_harvested
        else None,
        {
            "label": "Publisher",
            "value": current_publisher,
            "href": facet_url("publisher", ""),
            "aria": "Remove publisher filter: " + current_publisher,
        }
        if current_publisher
        else None,
    ]

    return render(
        request,
        "links_errors.html",
        {
            "title": f"Link errors ({shown_count:,})",
            "section": "links",
            "errors": page_rows,
            "filtered_errors": shown_count,
            "total_errors": stats.get("errors") or 0,
            "resolved_errors": stats.get("resolved") or 0,
            "check_rows": stats.get("total") or 0,
            "pills": pills,
            "facet_groups": facet_groups,
            "facet_qs": facet_qs,
            "facet_url": facet_url,
            "pager_base": pager_base,
            **pagination,
            "sort": sort,
            "dir": dir_,
        },
    )

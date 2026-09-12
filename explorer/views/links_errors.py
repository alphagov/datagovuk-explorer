"""GET /links/errors — the Link errors sub-report under Links.

Reads the `link_errors` table (ingested by scripts/ingest_link_errors.py
from data/errors-current.csv): every checked resource link across all
datasets — both check runs, and the OK/2xx rows that previously failed and
are now resolved (shown, styled positively, not filtered out). Sortable via
?sort= & ?dir=, filterable by outcome/category, domain (the host of the
broken URL), HTTP status (with the "No response" bucket for the code-less
DNS/timeout rows), harvest state (Harvested/Manual/Unknown) and publisher
via the single-select sidebar facets, paginated (100/page). Default sort is
URL (host) first.

The harvest state rides the datasets LEFT JOIN (queries/link_errors.py):
harvested/manual from the snapshot, unknown when the package is absent
from it (docs/link-errors-report.md §3 — derived, never stored). The
domain facet's host is derived too — split out of resource_url in SQL by
the same _URL_HOST expression the URL sort uses.

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

# Facet-group labels (sidebar order — to delete, outcome/category, domain,
# HTTP status, harvest state, publisher).
HARVEST_LABELS = dict(HARVEST_STATES)
TO_DELETE_LABELS = dict(TO_DELETE_VALUES)

def _category_name(value: str) -> str:
    """Display name for a raw category code (facet items and pills)."""
    return CATEGORY_LABELS.get(value, (value or "").title())


def _count_desc_values(counts: dict) -> list:
    """A {value: count} pool's keys ordered by descending count (ties by
    value) — the sidebar order for the small dict-returning facets (To
    delete, Harvested), so the list mirrors the counts shown next to it."""
    return sorted(counts, key=lambda value: (-counts[value], value))


def link_errors(request):
    """GET /links/errors — the link-check report with sidebar facets."""
    stats = link_errors_stats()

    # Filter-independent base pools (the validation whitelists) — the
    # no-filter facet counts, memoised. Only value validity is decided
    # here: the sidebar *order* is the filtered pool's count order below,
    # so selecting a facet re-sorts the sibling lists to the counts shown.
    base_pool = link_errors_facet_counts({})
    # value = org slug (the facet URL/filter key), name = display name.
    publisher_names = {p["value"]: p["name"] for p in base_pool["publishers"]}
    valid_categories = {c["value"] for c in base_pool["categories"]}
    valid_statuses = {s["value"] for s in base_pool["statuses"]}
    valid_domains = {h["value"] for h in base_pool["domains"]}
    valid_publishers = set(publisher_names)

    # Current facet selections — single-select per group, combinable across
    # groups; unknown values fall back to no selection.
    category = request.GET.get("category")
    current_category = category if category in valid_categories else None

    status = request.GET.get("status")
    current_status = status if status == "__none__" or status in valid_statuses else None

    domain = request.GET.get("domain")
    current_domain = "__none__" if domain == "__none__" else domain if domain in valid_domains else None

    to_delete = request.GET.get("to_delete")
    current_to_delete = to_delete if to_delete in TO_DELETE_LABELS else None

    harvested = request.GET.get("harvested")
    current_harvested = harvested if harvested in HARVEST_LABELS else None

    publisher = request.GET.get("publisher")
    current_publisher = publisher if publisher in valid_publishers else None

    # Domain/publisher facet state — every host and publisher is a facet;
    # the long lists collapse past their cutoffs behind the More toggles.
    domain_expanded = request.GET.get("domains") == "all"
    publisher_expanded = request.GET.get("publishers") == "all"
    # HTTP status list also collapses past the default cutoff behind its
    # "More statuses" toggle (?statuses=all).
    status_expanded = request.GET.get("statuses") == "all"

    filters = {
        "category": current_category,
        "status": current_status,
        "domain": current_domain,
        "to_delete": current_to_delete,
        "harvested": current_harvested,
        "publisher": current_publisher,
    }

    sort, dir_ = _sort_dir(request, LINK_ERRORS_SORT_COLUMNS, "url")

    # Count + page in SQL — only the page's rows are fetched (the LEFT
    # JOIN supplies org slug / harvest state / harvest source per row).
    stmts_out = link_errors_stmts(filters, sort, dir_)
    shown_count = stmts_out["count"].get(*stmts_out["params"])["n"]

    pagination = paginate(request, shown_count)
    page_rows = stmts_out["list"].all(*stmts_out["params"], pagination["page_size"], pagination["offset"])

    # Shared query-string machinery — ordered base (sort, dir, then each
    # active facet in a fixed order); facet_qs drops sort/dir for the
    # sort_link/pagination macros; facet_url sets/clears one facet value.
    # The extras carry the expanded-lists state (?domains=all /
    # ?publishers=all) so facet/sort/pager links keep the lists expanded.
    expanded_extras = {}
    if domain_expanded:
        expanded_extras["domains"] = "all"
    if publisher_expanded:
        expanded_extras["publishers"] = "all"
    if status_expanded:
        expanded_extras["statuses"] = "all"
    base_params = facets.preserve_params(
        sort,
        dir_,
        [
            ("category", current_category),
            ("status", current_status),
            ("domain", current_domain),
            ("to_delete", current_to_delete),
            ("harvested", current_harvested),
            ("publisher", current_publisher),
        ],
        expanded_extras or None,
    )
    facet_url = facets.facet_url_for(base_params)
    facet_qs = facets.facet_qs(base_params, include_sort=False)
    pager_base = facets.pager_base(base_params)

    # Sidebar facet groups — each group counts over the pool filtered by
    # every other group (the standard self-excluding sidebar), and each
    # list renders in that pool's own count order (desc), so selecting a
    # facet re-sorts the sibling lists to the counts actually shown. To
    # delete sits at the top: the checker's remove-from-catalogue
    # recommendation is the first thing a user decides before drilling
    # into why.
    pool = link_errors_facet_counts(filters)
    # The small dict-returning pools (to delete / harvested) sort by their
    # pool count too, not the canonical label order — one rule for every
    # facet list. Values with no rows in the pool are absent from these
    # dicts and simply don't render (facet_counts_group drops them).
    to_delete_master = [(value, TO_DELETE_LABELS[value]) for value in _count_desc_values(pool["to_delete"])]
    harvested_master = [(value, HARVEST_LABELS[value]) for value in _count_desc_values(pool["harvested"])]
    facet_groups = {
        g["key"]: g
        for g in (
            facets.facet_counts_group(
                "to_delete",
                "To delete",
                "Filter by the remove-link recommendation",
                to_delete_master,
                pool["to_delete"],
                current_to_delete,
                proportions=True,
            ),
            # Outcome and HTTP status mirror the host/publisher pattern: the
            # pool returns every category/status in it (count desc), so the
            # list is built from the same filtered rows its counts come from.
            facets.facet_counts_group(
                "category",
                "Outcome",
                "Filter by outcome",
                [(c["value"], _category_name(c["value"])) for c in pool["categories"]],
                {c["value"]: c["count"] for c in pool["categories"]},
                current_category,
                proportions=True,
            ),
            # The pool returns every domain in it (count desc), so master
            # and counts come from the same rows — the list mirrors the
            # current sibling-filter pool, not a global top-N.
            # Scheme-less/malformed URLs trail as the No URL bucket.
            facets.facet_counts_group(
                "domain",
                "Domain",
                "Filter by domain",
                [(h["value"], h["value"]) for h in pool["domains"]],
                {h["value"]: h["count"] for h in pool["domains"]},
                current_domain,
                proportions=True,
                plural="domains",
                toggle_base=base_params,
                expanded=domain_expanded,
                trailing=(
                    [
                        {
                            "value": "__none__",
                            "name": "No URL",
                            "count": pool["no_url"],
                            "active": current_domain == "__none__",
                        },
                    ]
                    if pool["no_url"]
                    else None
                ),
            ),
            facets.facet_counts_group(
                "status",
                "HTTP status",
                "Filter by HTTP status",
                [(s["value"], s["value"]) for s in pool["statuses"]],
                {s["value"]: s["count"] for s in pool["statuses"]},
                current_status,
                proportions=True,
                plural="statuses",
                toggle_base=base_params,
                expanded=status_expanded,
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
                harvested_master,
                pool["harvested"],
                current_harvested,
                proportions=True,
            ),
            # The pool returns every publisher in it (count desc), so master
            # and counts come from the same rows — the list mirrors the
            # current sibling-filter pool, not a global top-N. value is the
            # slug (the URL/filter key); name is the display name shown.
            facets.facet_counts_group(
                "publisher",
                "Publisher",
                "Filter by publisher",
                [(p["value"], p["name"]) for p in pool["publishers"]],
                {p["value"]: p["count"] for p in pool["publishers"]},
                current_publisher,
                proportions=True,
                plural="publishers",
                toggle_base=base_params,
                expanded=publisher_expanded,
            ),
        )
        if g is not None
    }

    # Decorate only the page's rows: the status cell text (code + category
    # name, or the category name alone for the code-less DNS/timeout rows).
    for r in page_rows:
        label = _category_name(r["category"])
        r["category_label"] = label
        r["ok"] = r["category"] == "OK"
        r["status_text"] = f"{r['status']} {label}" if r["status"] is not None else label

    # Pill labels for the active-filter strip (header left) — same order
    # as the sidebar facets (to delete, outcome, domain, status, harvested,
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
            "label": "Domain",
            "value": "No URL" if current_domain == "__none__" else current_domain,
            "href": facet_url("domain", ""),
            "aria": "Remove domain filter: " + ("No URL" if current_domain == "__none__" else current_domain),
        }
        if current_domain
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
            "value": publisher_names.get(current_publisher, current_publisher),
            "href": facet_url("publisher", ""),
            "aria": "Remove publisher filter: " + publisher_names.get(current_publisher, current_publisher),
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

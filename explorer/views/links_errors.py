"""GET /links/status — the Link status report under Links.

Reads `link_check_results` joined with `links`: every checked resource URL
across all datasets, one row per link occurrence. Sortable via ?sort= &
?dir=, filterable by outcome/category, domain, HTTP status, harvest state
and publisher via sidebar facets, paginated (100/page). Default sort is
URL (host) first.
"""

from django.shortcuts import render

from explorer import facets
from explorer.queries.link_errors import (
    CATEGORY_LABELS,
    HARVEST_STATES,
    LINK_ERRORS_SORT,
    LINK_ERRORS_SORT_DEFAULT,
    link_errors_facet_counts,
    link_errors_stats,
    link_errors_stmts,
)
from explorer.sort import parse_sort

from .core import _pill, paginate

HARVEST_LABELS = dict(HARVEST_STATES)


def _category_name(value: str) -> str:
    """Display name for a raw category code (facet items and pills)."""
    return CATEGORY_LABELS.get(value, (value or "").title())


def _count_desc_values(counts: dict) -> list:
    """A {value: count} pool's keys ordered by descending count (ties by
    value) — the sidebar order for the small dict-returning facets (To
    delete, Harvested), so the list mirrors the counts shown next to it."""
    return sorted(counts, key=lambda value: (-counts[value], value))


def link_errors(request):
    """GET /links/status — the link-check report with sidebar facets."""
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
    current_status = status if status in valid_statuses else None

    domain = request.GET.get("domain")
    current_domain = "__none__" if domain == "__none__" else domain if domain in valid_domains else None

    harvested = request.GET.get("harvested")
    current_harvested = harvested if harvested in HARVEST_LABELS else None

    publisher = request.GET.get("publisher")
    current_publisher = publisher if publisher in valid_publishers else None

    # Domain/publisher facet state — every host and publisher is a facet;
    # the long lists collapse past their cutoffs behind the More toggles.
    domain_expanded = request.GET.get("domains") == "all"
    publisher_expanded = request.GET.get("publishers") == "all"

    filters = {
        "category": current_category,
        "status": current_status,
        "domain": current_domain,
        "harvested": current_harvested,
        "publisher": current_publisher,
    }

    sort, dir_ = parse_sort(request, LINK_ERRORS_SORT, *LINK_ERRORS_SORT_DEFAULT)

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
    base_params = facets.preserve_params(
        sort,
        dir_,
        [
            ("category", current_category),
            ("status", current_status),
            ("domain", current_domain),
            ("harvested", current_harvested),
            ("publisher", current_publisher),
        ],
        expanded_extras or None,
        defaults=LINK_ERRORS_SORT_DEFAULT,
    )
    facet_url = facets.facet_url_for(base_params)
    facet_qs = facets.facet_qs(base_params, include_sort=False)
    pager_base = facets.pager_base(base_params)

    pool = link_errors_facet_counts(filters)
    # The small dict-returning pool (harvested) sorts by pool count, not
    # canonical label order — values absent from the pool don't render.
    harvested_master = [(value, HARVEST_LABELS[value]) for value in _count_desc_values(pool["harvested"])]
    facet_groups = {
        g["key"]: g
        for g in (
            # Outcome and HTTP status mirror the host/publisher pattern: the
            # pool returns every category/status in it (count desc), so the
            # list is built from the same filtered rows its counts come from.
            facets.facet_counts_group(
                "category",
                "Errors",
                "Filter by error type",
                [(c["value"], _category_name(c["value"])) for c in pool["categories"] if c["value"] != "OK"],
                {c["value"]: c["count"] for c in pool["categories"] if c["value"] != "OK"},
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
                "Status",
                "Filter by ok or error",
                [(s["value"], s["value"].title()) for s in pool["statuses"]],
                {s["value"]: s["count"] for s in pool["statuses"]},
                current_status,
                proportions=True,
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

    pills = [
        _pill("Errors", _category_name(current_category), facet_url("category", "")) if current_category else None,
        _pill("Domain", "No URL" if current_domain == "__none__" else current_domain, facet_url("domain", ""))
        if current_domain
        else None,
        _pill("Status", "No response" if current_status == "__none__" else current_status, facet_url("status", ""))
        if current_status
        else None,
        _pill("Harvested", HARVEST_LABELS[current_harvested], facet_url("harvested", ""))
        if current_harvested
        else None,
        _pill("Publisher", publisher_names.get(current_publisher, current_publisher), facet_url("publisher", ""))
        if current_publisher
        else None,
    ]

    return render(
        request,
        "links_errors.html",
        {
            "title": f"Link status ({shown_count:,})",
            "nav_key": "errors",
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

"""GET /links — every resource URL across all datasets.

Server-side sortable via ?sort= & ?dir=, filterable by domain, format
and created year via single-select facet links, paginated (100/page).

Facet sidebar counts are self-excluding SQL aggregates from
explorer/queries/links.py (links_facet_counts) over the same clause
builders the page list/count use (links_stmts) — each group applies the
other active filters, so a selected domain/format/created_year shrinks
the sibling counts (the same behaviour as /datasets). The report-header totals stay
fixed whole-table aggregates (LINKS_STATS).
"""

from django.shortcuts import render

from explorer import facets
from explorer.queries.links import (
    LINK_SORT_COLUMNS,
    links_facet_counts,
    links_stats,
    links_stmts,
)

from .core import _sort_dir, paginate

# Facet sidebar cutoffs — formats/domains beyond these hide behind their
# "More …" toggles (the standard facet-list expand/collapse; all other facet
# lists are always shown).
FORMAT_FACET_CUTOFF = 10
DOMAIN_FACET_CUTOFF = 10

# Hostnames — RFC 1035/2181 caps a fully-qualified name at 253 chars.
MAX_DOMAIN_LENGTH = 253


def links(request):
    """GET /links — the all-links report with sidebar facets."""
    stats = links_stats()
    no_url_links = stats.get("no_url") or 0

    # Sidebar facet pools — self-excluding SQL aggregates. The unfiltered
    # pools drive the format/created_year validation whitelists; the
    # filtered pools drive the sidebar counts once the selections are
    # validated.
    base_pool = links_facet_counts({})
    valid_formats = {f["fmt"] for f in base_pool["formats"]}
    valid_created_years = {r["created_year"] for r in base_pool["created_years"]}

    # Format facet — all formats are rendered to the page; the "More formats"
    # toggle expands/collapses the list client-side (with a ?formats=all
    # fallback when JS is off). formats_expanded only sets the initial state.
    formats_expanded = request.GET.get("formats") == "all"

    # Domain facet state — every host is a facet; the long list collapses
    # past DOMAIN_FACET_CUTOFF behind the same "More domains" toggle the
    # /links/errors domain facet uses (?domains=all, JS-free fallback).
    domain_expanded = request.GET.get("domains") == "all"

    # Validate against the full list so any format can be filtered even when
    # it's beyond the top 10 shown by default.
    # Facet values — bound as WHERE parameters, never interpolated.
    domain = request.GET.get("domain")
    current_domain = None
    if domain == "__none__":
        current_domain = "__none__"
    elif domain and len(domain) <= MAX_DOMAIN_LENGTH:
        current_domain = domain

    format_ = request.GET.get("format")
    current_format = "__none__" if format_ == "__none__" else format_ if format_ in valid_formats else None
    current_created_year = request.GET.get("created_year")
    current_created_year = (
        current_created_year if current_created_year in valid_created_years else None
    )

    sort, dir_ = _sort_dir(request, LINK_SORT_COLUMNS, "domain")

    filters = {"domain": current_domain, "format": current_format, "created_year": current_created_year}
    pool = links_facet_counts(filters)
    stmts_out = links_stmts(filters, sort, dir_)

    total = stmts_out["count"].get(*stmts_out["params"])["n"]
    pagination = paginate(request, total)
    link_rows = stmts_out["list"].all(*stmts_out["params"], pagination["page_size"], pagination["offset"])

    # Query-string fragments shared by sort links / facet links / pills.
    # Dicts preserve insertion order, so urlencode emits the fixed
    # parameter order: sort, dir, then domain, format, created_year,
    # formats, domains. The extras carry the expanded-lists state
    # (?formats=all / ?domains=all) so facet/sort/pager links keep the
    # lists expanded.
    expanded_extras = {}
    if formats_expanded:
        expanded_extras["formats"] = "all"
    if domain_expanded:
        expanded_extras["domains"] = "all"
    base_params = facets.preserve_params(
        sort,
        dir_,
        [
            ("domain", current_domain),
            ("format", current_format),
            ("created_year", current_created_year),
        ],
        expanded_extras or None,
    )
    facet_url = facets.facet_url_for(base_params)

    # Extra query string preserving the active facets (for sort/pagination links)
    facet_qs = facets.facet_qs(base_params, include_sort=False)
    # ?-prefixed base for the pager links (sort/dir + active facets)
    pager_base = facets.pager_base(base_params)

    # Facet groups for the sidebar (pool counts + current selection -> group)
    facet_groups = [
        group
        for group in (
            # The pool returns every domain in it (count desc), so master and
            # counts come from the same rows — the list mirrors the current
            # sibling-filter pool, not a global top-N. Scheme-less URLs trail
            # as the No URL bucket.
            facets.facet_counts_group(
                "domain",
                "Domain",
                "Filter by domain",
                [(d["domain"], d["domain"]) for d in pool["domains"]],
                {d["domain"]: d["count"] for d in pool["domains"]},
                current_domain,
                proportions=True,
                cutoff=DOMAIN_FACET_CUTOFF,
                toggle_base=base_params,
                toggle_param="domains",
                toggle_label="domains",
                expanded=domain_expanded,
                list_id="domain-facet-list",
                search="Search domains",
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
                "format",
                "Format",
                "Filter by format",
                [(f["fmt"], f["fmt"]) for f in pool["formats"]],
                {f["fmt"]: f["count"] for f in pool["formats"]},
                current_format,
                proportions=True,
                cutoff=FORMAT_FACET_CUTOFF,
                toggle_base=base_params,
                toggle_param="formats",
                toggle_label="formats",
                expanded=formats_expanded,
                list_id="format-facet-list",
                trailing=(
                    [
                        {
                            "value": "__none__",
                            "name": "No format",
                            "count": pool["no_format"],
                            "active": current_format == "__none__",
                        },
                    ]
                    if pool["no_format"]
                    else None
                ),
            ),
            facets.facet_counts_group(
                "created_year",
                "Year created",
                "Filter by year created",
                [(r["created_year"], r["created_year"]) for r in pool["created_years"]],
                {r["created_year"]: r["count"] for r in pool["created_years"]},
                current_created_year,
                proportions=True,
            ),
        )
        if group is not None
    ]

    return render(
        request,
        "links.html",
        {
            "title": "Links — data.gov.uk Explorer",
            "section": "links",
            "links": link_rows,
            "facet_groups": facet_groups,
            "current_domain": current_domain,
            "current_format": current_format,
            "current_created_year": current_created_year,
            "facet_qs": facet_qs,
            "facet_url": facet_url,
            "pager_base": pager_base,
            "total_links": stats.get("total") or 0,
            "filtered_links": total,
            "no_url_links": no_url_links,
            "internal_links": stats.get("internal") or 0,
            "external_links": (stats.get("total") or 0) - (stats.get("internal") or 0) - no_url_links,
            "total_orgs": stats.get("orgs") or 0,
            **pagination,
            "sort": sort,
            "dir": dir_,
        },
    )

"""GET /links — every resource URL across all datasets.

Server-side sortable via ?sort= & ?dir=, filterable by domain, format
and created year via single-select facet links, paginated (100/page).
GET /links/download.csv — the same filtered, sorted rows as a CSV
attachment, unpaginated.

Facet sidebar counts are self-excluding SQL aggregates from
explorer/queries/links.py (links_facet_counts) over the same clause
builders the page list/count use (links_stmts) — each group applies the
other active filters, so a selected domain/format/created_year shrinks
the sibling counts (the same behaviour as /datasets). The report-header totals stay
fixed whole-table aggregates (LINKS_STATS).
"""

from django.shortcuts import render

from explorer import facets
from explorer.csv_export import csv_response
from explorer.queries.core import iter_rows
from explorer.queries.links import (
    LINK_SORT,
    LINK_SORT_DEFAULT,
    links_facet_counts,
    links_stats,
    links_stmts,
)
from explorer.sort import parse_sort

from .core import paginate, pill

# Hostnames — RFC 1035/2181 caps a fully-qualified name at 253 chars.
MAX_DOMAIN_LENGTH = 253


def _listing(request) -> dict:
    """Resolve one /links request into its validated filters, sort state and
    compiled count+list statements — shared by the page and the CSV download
    so the exported rows can't drift from the table."""
    # Filter-independent pools — the validation whitelists and the
    # publisher display names (memoised by links_facet_counts' unfiltered
    # cache, so the page's own base_pool lookup is free).
    base_pool = links_facet_counts({})
    valid_formats = {f["fmt"] for f in base_pool["formats"]}
    valid_created_years = {r["created_year"] for r in base_pool["created_years"]}
    publisher_names = {p["value"]: p["name"] for p in base_pool["publishers"]}
    valid_publishers = set(publisher_names)

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
    current_created_year = current_created_year if current_created_year in valid_created_years else None
    publisher = request.GET.get("publisher")
    current_publisher = publisher if publisher in valid_publishers else None

    sort, dir_ = parse_sort(request, LINK_SORT, *LINK_SORT_DEFAULT)

    filters = {
        "domain": current_domain,
        "format": current_format,
        "created_year": current_created_year,
        "publisher": current_publisher,
    }
    stmts = links_stmts(filters, sort, dir_)
    return {
        "filters": filters,
        "publisher_names": publisher_names,
        "sort": sort,
        "dir": dir_,
        "stmts": stmts,
        "total": stmts["count"].get(*stmts["params"])["n"],
    }


# CSV export columns — the table's own columns (Name uses the resource_name
# macro's fallback: name or description; Domain dropped — the host is
# recoverable from URL), then the two entity GUIDs last so every export is
# joinable to the source records. URL is kept beside Name because it is the
# row's real identity, matching the /report/links export.
_LINKS_CSV_COLUMNS = [
    ("Name", "name"),
    ("URL", "url"),
    ("Format", "format"),
    ("Dataset", "dataset_title"),
    ("Publisher", "org_display_name"),
    ("Dataset ID", "ckan_id"),
    ("Resource ID", "resource_id"),
]


def _csv_row(r: dict) -> dict:
    """One SQL row → its export shape: the Name fallback the resource_name
    macro renders, plus the raw columns."""
    return {
        "name": r["name"] or r["description"],
        "url": r["url"],
        "format": r["format"],
        "dataset_title": r["dataset_title"],
        "org_display_name": r["org_display_name"],
        "ckan_id": r["ckan_id"],
        "resource_id": r["resource_id"],
    }


def links(request):
    """GET /links — the all-links report with sidebar facets."""
    stats = links_stats()
    no_url_links = stats.get("no_url") or 0

    # Format list — collapses past the default cutoff behind its "More
    # formats" toggle (?formats=all fallback when JS is off).
    formats_expanded = request.GET.get("formats") == "all"

    # Domain facet state — every host is a facet; the long list collapses
    # past the default cutoff behind the "More domains" toggle the
    # /links/errors domain facet uses (?domains=all, JS-free fallback).
    domain_expanded = request.GET.get("domains") == "all"

    # Created-year list also collapses past the default cutoff behind its
    # "More created years" toggle (?created_years=all).
    created_year_expanded = request.GET.get("created_years") == "all"

    # Publisher list collapses past the default cutoff behind its
    # "More publishers" toggle (?publishers=all).
    publisher_expanded = request.GET.get("publishers") == "all"

    listing = _listing(request)
    filters = listing["filters"]
    sort, dir_ = listing["sort"], listing["dir"]
    current_domain = filters["domain"]
    current_format = filters["format"]
    current_created_year = filters["created_year"]
    current_publisher = filters["publisher"]

    pool = links_facet_counts(filters)
    total = listing["total"]
    pagination = paginate(request, total)
    link_rows = listing["stmts"]["list"].all(*listing["stmts"]["params"], pagination["page_size"], pagination["offset"])

    # Query-string fragments shared by sort links / facet links / pills.
    # Dicts preserve insertion order, so urlencode emits the fixed parameter
    # order: sort, dir, then domain, format, created_year, publisher. The
    # extras carry the expanded-lists state so facet/sort/pager links keep
    # the lists expanded.
    expanded_extras = {}
    if formats_expanded:
        expanded_extras["formats"] = "all"
    if domain_expanded:
        expanded_extras["domains"] = "all"
    if created_year_expanded:
        expanded_extras["created_years"] = "all"
    if publisher_expanded:
        expanded_extras["publishers"] = "all"
    base_params = facets.preserve_params(
        sort,
        dir_,
        [
            ("domain", current_domain),
            ("format", current_format),
            ("created_year", current_created_year),
            ("publisher", current_publisher),
        ],
        expanded_extras or None,
        defaults=LINK_SORT_DEFAULT,
    )
    facet_url = facets.facet_url_for(base_params)

    # Extra query string preserving the active facets (for sort/pagination links)
    facet_qs = facets.facet_qs(base_params, include_sort=False)
    # ?-prefixed base for the pager links (sort/dir + active facets)
    pager_base = facets.pager_base(base_params)

    # Facet groups for the sidebar (pool counts + current selection -> group)
    facet_groups = {
        g["key"]: g
        for g in (
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
                "format",
                "Format",
                "Filter by format",
                [(f["fmt"], f["fmt"]) for f in pool["formats"]],
                {f["fmt"]: f["count"] for f in pool["formats"]},
                current_format,
                proportions=True,
                plural="formats",
                toggle_base=base_params,
                expanded=formats_expanded,
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
                plural="created years",
                toggle_base=base_params,
                expanded=created_year_expanded,
            ),
            # The pool returns every publisher in it (count desc), so master
            # and counts come from the same rows. value = org_slug (the URL/
            # filter key); name = display name shown.
            facets.facet_counts_group(
                "publisher",
                "Publisher",
                "Filter by publisher",
                [(p["value"], p["name"] or p["value"]) for p in pool["publishers"]],
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

    domain_name = "No URL" if current_domain == "__none__" else current_domain
    format_name = "No format" if current_format == "__none__" else current_format
    publisher_names = listing["publisher_names"]
    publisher_label = publisher_names.get(current_publisher, current_publisher) if current_publisher else None
    pills = [
        pill("Domain", domain_name, facet_url("domain", "")) if current_domain else None,
        pill("Format", format_name, facet_url("format", "")) if current_format else None,
        pill("Created year", current_created_year, facet_url("created_year", "")) if current_created_year else None,
        pill("Publisher", publisher_label, facet_url("publisher", "")) if current_publisher else None,
    ]

    return render(
        request,
        "links.html",
        {
            "title": "Links — data.gov.uk Explorer",
            "nav_key": "links",
            "links": link_rows,
            "facet_groups": facet_groups,
            "pills": pills,
            "facet_qs": facet_qs,
            "facet_url": facet_url,
            "pager_base": pager_base,
            "download_url": f"/links/download.csv{pager_base}",
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


def links_download(request):
    """GET /links/download.csv — the same filtered, sorted links as the
    table, unpaginated and as a CSV attachment."""
    listing = _listing(request)
    rows = (_csv_row(r) for r in iter_rows(listing["stmts"]))
    return csv_response("links.csv", _LINKS_CSV_COLUMNS, rows)

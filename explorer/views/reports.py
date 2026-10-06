"""GET /report/{key} — one data-quality finding per page.

GET /report/{key}               — one paginated report per finding, with
                                   optional single-select org facet (?org=)
GET /report/{key}?url=...         — duplicate-URL detail mode
                                     (links-duplicate-urls)
GET /report/{key}?hash=...        — duplicate-content detail mode
                                     (datasets-duplicate-content)
GET /report/{key}/download.csv    — the same filtered, sorted rows as CSV,
                                     unpaginated (?page= is ignored)

The home dashboard (GET /) is views/dashboard.py; its card data is
assembled in queries/dashboard.py.
"""

import csv
import io
import json
from datetime import date, datetime

from django.http import Http404, HttpResponse
from django.shortcuts import render

from explorer import facets
from explorer.queries.core import Query
from explorer.queries.reports import (
    DATASET_REPORT_NULLS_LAST,
    DATASET_REPORT_SORT,
    DATASET_REPORT_SORT_DEFAULT,
    DUPLICATE_CONTENT_SORT,
    DUPLICATE_CONTENT_SORT_DEFAULT,
    DUPLICATE_URL_SORT,
    DUPLICATE_URL_SORT_DEFAULT,
    LINK_REPORT_SORT,
    LINK_REPORT_SORT_DEFAULT,
    REPORTS,
    SUSPICIOUS_REDIRECT_SORT,
    SUSPICIOUS_REDIRECT_SORT_DEFAULT,
    report_facet_counts,
    report_stmts,
    report_unfiltered_count,
    report_unfiltered_options,
)
from explorer.sort import order_by as _order_by_sql, parse_sort

from .core import paginate, pill

# Facet plural noun phrases — the "More …" text and, slugged (spaces →
# underscores), the ?<plural>=all expand param for each report facet key.
# Facets without an entry render fully shown (no collapse).
REPORT_FACET_PLURALS = {
    "org": "publishers",
    "api_category": "categories",
    "api_type": "api types",
}

# Sort columns and defaults for each report kind.
_REPORT_SORT = {
    "datasets": (DATASET_REPORT_SORT, DATASET_REPORT_SORT_DEFAULT),
    "links": (LINK_REPORT_SORT, LINK_REPORT_SORT_DEFAULT),
    "duplicate-content": (DUPLICATE_CONTENT_SORT, DUPLICATE_CONTENT_SORT_DEFAULT),
    "duplicate-urls": (DUPLICATE_URL_SORT, DUPLICATE_URL_SORT_DEFAULT),
    "suspicious-redirects": (SUSPICIOUS_REDIRECT_SORT, SUSPICIOUS_REDIRECT_SORT_DEFAULT),
}
_NO_SORT = ({}, ("name", "asc"))

_DUPLICATE_CONTENT_DETAIL_SORT_DEFAULT = ("metadata_created", "asc")

# The CSV export's "no pagination" limit. The list statements all end in
# LIMIT %s OFFSET %s, so the download runs the same compiled SQL with a
# limit no report could reach (the largest is well under 100k) and offset 0,
# keeping the exported column set and the page's in lockstep.
_DOWNLOAD_ROW_LIMIT = 1_000_000

# CSV export columns per listing shape: (header, row key). The detail modes
# reuse the "datasets"/"links" shapes and drop columns via hidden_cols, so
# the CSV mirrors what the table shows. "title"/"name" get the table's own
# fallbacks in _csv_cell (title or name; name or description).
_CSV_COLUMNS = {
    "datasets": [
        ("Dataset", "title"),
        ("Publisher", "org_display_name"),
        ("Created", "metadata_created"),
        ("Modified", "metadata_modified"),
        ("Views", "views"),
    ],
    "links": [
        ("Name", "name"),
        ("URL", "url"),
        ("Format", "format"),
        ("Dataset", "dataset_title"),
        ("Publisher", "org_display_name"),
    ],
    "duplicate-urls": [
        ("URL", "url"),
        ("Datasets", "dataset_count"),
        ("Publishers", "org_count"),
    ],
    "suspicious-redirects": [
        ("Final URL", "final_url"),
        ("Links", "link_count"),
        ("Publishers", "org_count"),
    ],
    "duplicate-content": [
        ("Title", "title"),
        ("Datasets", "dataset_count"),
        ("Publishers", "org_count"),
    ],
}


def _report(key):
    report = next((r for r in REPORTS if r["key"] == key), None)
    if report is None:
        raise Http404
    return report


# ── Listing builders ──────────────────────────────────────────────────────
# Each reports request (a report's own list, or one of its detail modes)
# resolves to a *listing*: the compiled list statement + params, the row
# count, the active sort and the query-string base. The page and the CSV
# download both build from this one dict, so filters/sort/columns can't
# drift between what's shown and what's exported. Facet counts and pills
# are page-only extras the main listing carries; detail modes have none.


def _main_listing(request, report):
    """The report's own paginated list, narrowed by its facet selections."""
    kind = report["kind"]
    sort_cols, sort_defaults = _REPORT_SORT.get(kind, _NO_SORT)
    sort, dir_ = parse_sort(request, sort_cols, *sort_defaults)

    expanded = {}
    for facet_key, plural in REPORT_FACET_PLURALS.items():
        if request.GET.get(plural.replace(" ", "_")) == "all":
            expanded[facet_key] = True
    facet_groups, active_filters, active_facets, base_params = _report_facets(
        report,
        {
            "org": request.GET.get("org"),
            "api_category": request.GET.get("api_category"),
            "api_type": request.GET.get("api_type"),
        },
        expanded,
        sort=sort,
        dir_=dir_,
        sort_defaults=sort_defaults,
    )

    facet_url = facets.facet_url_for(base_params)
    stmt = report_stmts(report, active_filters, sort=sort, dir_=dir_)
    # No-filter count is memoised per report key (build-time snapshot);
    # filtered counts run live (per-combo SQL).
    total = report_unfiltered_count(report["key"]) if not active_filters else stmt["count"].get(*stmt["params"])["n"]
    pills = [pill(f["label"], f["current_name"], facet_url(f["key"], "")) for f in active_facets]

    return {
        "sort": sort,
        "dir": dir_,
        "stmt": stmt,
        "total": total,
        "base_params": base_params,
        "facet_groups": facet_groups,
        "facet_url": facet_url,
        "pills": pills,
    }


def _duplicate_url_listing(request, report, url):
    """Duplicate-URLs detail mode (?url=<encoded-url>) — every dataset that
    links to one shared URL."""
    sort, dir_ = parse_sort(request, LINK_REPORT_SORT, *LINK_REPORT_SORT_DEFAULT)
    order_sql = _order_by_sql(LINK_REPORT_SORT, sort, dir_, "LOWER(dataset_title), id")
    stmt = {"list": Query(report["detail_sql"].replace("{order_by}", order_sql)), "params": [url]}
    total = Query(report["detail_count_sql"]).get(url)["n"]
    base_params = facets.preserve_params(sort, dir_, [("url", url)], defaults=LINK_REPORT_SORT_DEFAULT)
    return {
        "title": "Duplicate URL — data.gov.uk Explorer",
        "kind": "links",
        "hidden_cols": {"url"},
        "detail_url": url,
        "sort": sort,
        "dir": dir_,
        "stmt": stmt,
        "total": total,
        "base_params": base_params,
    }


def _suspicious_redirect_listing(request, report, url):
    """Suspicious-redirects detail mode (?url=<encoded-url>) — every link
    that redirects to this shared destination."""
    sort, dir_ = parse_sort(request, LINK_REPORT_SORT, *LINK_REPORT_SORT_DEFAULT)
    order_sql = _order_by_sql(LINK_REPORT_SORT, sort, dir_, "LOWER(dataset_title), id")
    stmt = {"list": Query(report["detail_sql"].replace("{order_by}", order_sql)), "params": [url]}
    total = Query(report["detail_count_sql"]).get(url)["n"]
    base_params = facets.preserve_params(sort, dir_, [("url", url)], defaults=LINK_REPORT_SORT_DEFAULT)
    return {
        "title": "Suspicious redirect — data.gov.uk Explorer",
        "kind": "links",
        "hidden_cols": set(),
        "detail_url": url,
        "sort": sort,
        "dir": dir_,
        "stmt": stmt,
        "total": total,
        "base_params": base_params,
    }


def _duplicate_content_listing(request, report, content_hash):
    """Duplicate-content detail mode (?hash=<md5>) — every dataset that
    shares one identical title/notes/resource-URL-set hash."""
    sort, dir_ = parse_sort(request, DATASET_REPORT_SORT, *_DUPLICATE_CONTENT_DETAIL_SORT_DEFAULT)
    order_sql = _order_by_sql(
        DATASET_REPORT_SORT,
        sort,
        dir_,
        "LOWER(title), id",
        nulls_last=DATASET_REPORT_NULLS_LAST,
    )
    stmt = {"list": Query(report["detail_sql"].replace("{order_by}", order_sql)), "params": [content_hash]}
    total = Query(report["detail_count_sql"]).get(content_hash)["n"]
    base_params = facets.preserve_params(
        sort,
        dir_,
        [("hash", content_hash)],
        defaults=_DUPLICATE_CONTENT_DETAIL_SORT_DEFAULT,
    )
    return {
        "title": "Duplicate dataset content — data.gov.uk Explorer",
        "kind": "datasets",
        "hidden_cols": set(),
        "detail_hash": content_hash,
        "sort": sort,
        "dir": dir_,
        "stmt": stmt,
        "total": total,
        "base_params": base_params,
    }


def _listing(request, report):
    """Dispatch one request to the right listing builder — detail mode when
    its param is present, otherwise the report's own list."""
    url = request.GET.get("url")
    content_hash = request.GET.get("hash")
    if report["kind"] == "duplicate-urls" and url is not None:
        return _duplicate_url_listing(request, report, url)
    if report["kind"] == "suspicious-redirects" and url is not None:
        return _suspicious_redirect_listing(request, report, url)
    if report["kind"] == "duplicate-content" and content_hash is not None:
        return _duplicate_content_listing(request, report, content_hash)
    return _main_listing(request, report)


# ── Listing → page context / CSV ─────────────────────────────────────────


def _listing_hidden_cols(report, listing) -> set:
    if "hidden_cols" in listing:
        return listing["hidden_cols"]
    return set(report.get("hidden_cols", []))


def _listing_kind(report, listing) -> str:
    return listing.get("kind") or report["kind"]


def _listing_show_api_links(report, listing) -> bool:
    return listing.get("show_api_links", report.get("show_api_links", False))


def _page_context(report, listing, rows, pagination) -> dict:
    """The report.html context for one listing: the current-dict the
    template renders, the facet/pill machinery (main listing only), the
    pager base and the CSV download URL built from the same query base."""
    base_params = listing["base_params"]
    pager_base = facets.pager_base(base_params)
    return {
        "title": listing.get("title") or f"{report['label']} — data.gov.uk Explorer",
        "nav_key": "dashboard",
        "current": {
            "key": report["key"],
            "label": report["label"],
            "description": report["description"],
            "kind": _listing_kind(report, listing),
            "count": listing["total"],
            "hidden_cols": _listing_hidden_cols(report, listing),
            "show_api_links": _listing_show_api_links(report, listing),
        },
        "facet_groups": listing.get("facet_groups", {}),
        "pills": listing.get("pills", []),
        "facet_url": listing.get("facet_url"),
        "facet_qs": facets.facet_qs(base_params, include_sort=False),
        "pager_base": pager_base,
        "download_url": f"/report/{report['key']}/download.csv{pager_base}",
        "detail_url": listing.get("detail_url"),
        "detail_hash": listing.get("detail_hash"),
        "sort": listing["sort"],
        "dir": listing["dir"],
        "rows": rows,
        **pagination,
    }


def _parse_api_links(rows: list[dict]) -> list[dict]:
    """datasets-has-api: api_links arrives as a jsonb string (the query
    layer's psycopg str loader — jsonb comes back as a JSON string here)
    — parse it into a list of {name, format, url} dicts so the template
    and the CSV can render the matched resources."""
    rows = [dict(r) for r in rows]
    for row in rows:
        row["api_links"] = json.loads(row["api_links"]) if row.get("api_links") else []
    return rows


def _csv_columns(report, listing) -> list[tuple[str, str]]:
    """The export's (header, key) columns — the listing's shape minus its
    hidden columns, plus the API-links column when the report has one."""
    columns = [
        (header, key)
        for header, key in _CSV_COLUMNS[_listing_kind(report, listing)]
        if key not in _listing_hidden_cols(report, listing)
    ]
    if _listing_show_api_links(report, listing):
        columns.append(("API links", "api_links"))
    return columns


def _csv_cell(row: dict, key: str):
    """One cell's CSV value. Mirrors the table's own fallbacks ("Dataset"
    is title or name; "Name" is name or description) and serialises dates
    to ISO so spreadsheets parse them."""
    if key == "title":
        value = row.get("title") or row.get("name")
    elif key == "name":
        value = row.get("name") or row.get("description")
    elif key == "api_links":
        return "; ".join(
            " — ".join(part for part in (link.get("name"), link.get("url")) if part)
            for link in row.get("api_links") or []
        )
    else:
        value = row.get(key)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None:
        return ""
    return value


def _csv_response(report, listing, rows) -> HttpResponse:
    """Render one listing as a downloadable CSV attachment (BOM included so
    Excel reads the UTF-8 names correctly)."""
    columns = _csv_columns(report, listing)
    buffer = io.StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer)
    writer.writerow([header for header, _ in columns])
    for row in rows:
        writer.writerow([_csv_cell(row, key) for _, key in columns])
    response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{report["key"]}.csv"'
    return response


def _report_facets(
    report,
    query_params,
    expanded,
    *,
    sort="name",
    dir_="asc",
    sort_defaults=("name", "asc"),
) -> tuple[dict, dict, list, dict]:
    """The report's facet groups + active selections for one request,
    validated against the report's own unfiltered facet options.

    Counts are self-excluding (queries/reports.py's report_facet_counts):
    each group applies the other active facets' filters, omitting its own.
    The base params are built here so the More toggles and the caller's
    facet_url/pager links share them. Returns (facet_groups,
    active_filters, active_facets, base_params)."""
    facet_groups = {}
    active_filters: dict[str, str] = {}
    active_facets: list[dict] = []

    # Pass 1 — validate each requested value against the report's own
    # unfiltered option pool (self-exclusion affects counts, not validity).
    # The unfiltered pools are memoised per report key (build-time
    # snapshot); the view runs them on every request even when a facet is
    # selected, so this is what keeps the heavy has-api pools cached.
    unfiltered_options = report_unfiltered_options(report["key"])
    for facet in report.get("facets", []):
        options = unfiltered_options[facet["key"]]
        wanted = query_params.get(facet["key"])
        if wanted is not None:
            match = next((o for o in options if o["slug"] == wanted), None)
            if match:
                active_filters[facet["key"]] = match["slug"]
                active_facets.append(
                    {
                        "key": facet["key"],
                        "label": facet["label"],
                        "current_name": match["name"],
                    },
                )

    extras = {}
    for key, plural in REPORT_FACET_PLURALS.items():
        if expanded.get(key):
            extras[plural.replace(" ", "_")] = "all"
    base_params = facets.preserve_params(
        sort,
        dir_,
        list(active_filters.items()),
        extras or None,
        defaults=sort_defaults,
    )

    # Pass 2 — self-excluding counts with the complete active-filter set.
    # No active filters → the pools are the memoised unfiltered ones; with
    # filters the counts are computed live (self-excluding, per-combo SQL).
    counts_stmt = report_facet_counts(report, active_filters)
    for facet in report.get("facets", []):
        if active_filters:
            sql, params = counts_stmt[facet["key"]]
            options = Query(sql).all(*params)
        else:
            options = unfiltered_options[facet["key"]]
        current = active_filters.get(facet["key"])
        group = facets.facet_counts_group(
            facet["key"],
            facet["label"],
            f"Filter by {facet['label'].lower()}",
            [(o["slug"], o["name"]) for o in options],
            {o["slug"]: o["count"] for o in options},
            current,
            proportions=True,
            plural=REPORT_FACET_PLURALS.get(facet["key"]),
            toggle_base=base_params,
            expanded=bool(expanded.get(facet["key"])),
        )
        if group is not None:
            facet_groups[group["key"]] = group
    return facet_groups, active_filters, active_facets, base_params


def report(request, key):
    """GET /report/{key} — one data-quality finding, paginated via ?page=.

    Duplicate-URL detail mode (?url=) lists every dataset that links to one
    shared URL. Otherwise the report's own single-select facets narrow the
    report: ?org=<slug> (all faceted reports) and ?api_type=<slug> (the
    "Datasets with an API" report's API-type facet).
    """
    report = _report(key)
    listing = _listing(request, report)
    pagination = paginate(request, listing["total"])
    rows = listing["stmt"]["list"].all(
        *listing["stmt"]["params"],
        pagination["page_size"],
        pagination["offset"],
    )
    if report.get("show_api_links"):
        rows = _parse_api_links(rows)
    return render(request, "report.html", _page_context(report, listing, rows, pagination))


def report_download(request, key):
    """GET /report/{key}/download.csv — the same filtered, sorted rows as
    the page, but unpaginated (?page= is ignored) and as a CSV attachment.

    Mirrors report()'s listing exactly (same query base), so the file can't
    disagree with the table it was downloaded from.
    """
    report = _report(key)
    listing = _listing(request, report)
    rows = listing["stmt"]["list"].all(*listing["stmt"]["params"], _DOWNLOAD_ROW_LIMIT, 0)
    if report.get("show_api_links"):
        rows = _parse_api_links(rows)
    return _csv_response(report, listing, rows)

"""GET /report/{key} — one data-quality finding per page.

GET /report/{key}        — one paginated report per finding, with optional
                            single-select org facet (?org=)
GET /report/{key}?url=...  — duplicate-URL detail mode (links-duplicate-urls)
GET /report/{key}?hash=... — duplicate-content detail mode
                              (datasets-duplicate-content)

The home dashboard (GET /) is views/dashboard.py; its card data is
assembled in queries/dashboard.py.
"""

import json

from django.http import Http404
from django.shortcuts import render

from explorer import facets
from explorer.queries.core import Query
from explorer.queries.reports import (
    DATASET_REPORT_SORT,
    DATASET_REPORT_SORT_DEFAULT,
    DUPLICATE_CONTENT_SORT,
    DUPLICATE_CONTENT_SORT_DEFAULT,
    DUPLICATE_URL_SORT,
    DUPLICATE_URL_SORT_DEFAULT,
    LINK_REPORT_SORT,
    LINK_REPORT_SORT_DEFAULT,
    REPORTS,
    report_facet_counts,
    report_stmts,
    report_unfiltered_count,
    report_unfiltered_options,
)
from explorer.sort import order_by as _order_by_sql, parse_sort

from .core import _pill, paginate

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
}
_NO_SORT = ({}, ("name", "asc"))

_DUPLICATE_CONTENT_DETAIL_SORT_DEFAULT = ("metadata_created", "asc")


def _duplicate_url_report(request, report, url):
    """Duplicate-URLs detail mode (?url=<encoded-url>) — every dataset that
    links to one shared URL."""
    sort, dir_ = parse_sort(request, LINK_REPORT_SORT, *LINK_REPORT_SORT_DEFAULT)
    order_sql = _order_by_sql(LINK_REPORT_SORT, sort, dir_, "LOWER(dataset_title), id")
    list_stmt = Query(report["detail_sql"].replace("{order_by}", order_sql))

    count_stmt = Query(report["detail_count_sql"])
    total = count_stmt.get(url)["n"]

    pagination = paginate(request, total)
    rows = list_stmt.all(url, pagination["page_size"], pagination["offset"])

    base_params = facets.preserve_params(sort, dir_, [("url", url)], defaults=LINK_REPORT_SORT_DEFAULT)
    facet_qs = facets.facet_qs(base_params, include_sort=False)
    pager_base = facets.pager_base(base_params)

    return render(
        request,
        "report.html",
        {
            "title": "Duplicate URL — data.gov.uk Explorer",
            "nav_key": "dashboard",
            "current": {
                "key": report["key"],
                "label": report["label"],
                "description": report["description"],
                "kind": "links",
                "count": total,
                "hidden_cols": {"url"},
            },
            "detail_url": url,
            "pills": [],
            "sort": sort,
            "dir": dir_,
            "facet_qs": facet_qs,
            "pager_base": pager_base,
            "rows": rows,
            **pagination,
        },
    )


def _duplicate_content_report(request, report, content_hash):
    """Duplicate-content detail mode (?hash=<md5>) — every dataset that
    shares one identical title/notes/resource-URL-set hash."""
    sort, dir_ = parse_sort(request, DATASET_REPORT_SORT, *_DUPLICATE_CONTENT_DETAIL_SORT_DEFAULT)
    order_sql = _order_by_sql(DATASET_REPORT_SORT, sort, dir_, "LOWER(title), id")
    list_stmt = Query(report["detail_sql"].replace("{order_by}", order_sql))

    count_stmt = Query(report["detail_count_sql"])
    total = count_stmt.get(content_hash)["n"]

    pagination = paginate(request, total)
    rows = list_stmt.all(content_hash, pagination["page_size"], pagination["offset"])

    base_params = facets.preserve_params(
        sort, dir_, [("hash", content_hash)], defaults=_DUPLICATE_CONTENT_DETAIL_SORT_DEFAULT,
    )
    facet_qs = facets.facet_qs(base_params, include_sort=False)
    pager_base = facets.pager_base(base_params)

    return render(
        request,
        "report.html",
        {
            "title": "Duplicate dataset content — data.gov.uk Explorer",
            "nav_key": "dashboard",
            "current": {
                "key": report["key"],
                "label": report["label"],
                "description": report["description"],
                "kind": "datasets",
                "count": total,
                "hidden_cols": set(),
            },
            "detail_hash": content_hash,
            "pills": [],
            "sort": sort,
            "dir": dir_,
            "facet_qs": facet_qs,
            "pager_base": pager_base,
            "rows": rows,
            **pagination,
        },
    )


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
    report = next((r for r in REPORTS if r["key"] == key), None)
    if report is None:
        raise Http404

    url = request.GET.get("url")
    content_hash = request.GET.get("hash")

    # Duplicate URLs detail mode: ?url=<encoded-url>
    if report["kind"] == "duplicate-urls" and url is not None:
        return _duplicate_url_report(request, report, url)

    # Duplicate content detail mode: ?hash=<md5>
    if report["kind"] == "duplicate-content" and content_hash is not None:
        return _duplicate_content_report(request, report, content_hash)

    kind = report["kind"]
    sort_cols, sort_defaults = _REPORT_SORT.get(kind, _NO_SORT)
    sort, dir_ = parse_sort(request, sort_cols, *sort_defaults)

    # Optional single-select facets (?org=<slug>, ?api_type=<slug>...). Each
    # report defines its own `facets` list; the selected values are validated
    # against the compiled facet options before being used as filters.
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

    # Query-string machinery — facet_url_for for the facet links and pills;
    # pager_base includes sort so pagination preserves the chosen column.
    facet_url = facets.facet_url_for(base_params)
    facet_qs = facets.facet_qs(base_params, include_sort=False)
    pager_base = facets.pager_base(base_params)

    stmt = report_stmts(report, active_filters, sort=sort, dir_=dir_)
    # No-filter count is memoised per report key (build-time snapshot);
    # filtered counts run live (per-combo SQL).
    total = report_unfiltered_count(report["key"]) if not active_filters else stmt["count"].get(*stmt["params"])["n"]

    pagination = paginate(request, total)

    rows = stmt["list"].all(*stmt["params"], pagination["page_size"], pagination["offset"])

    # datasets-has-api: api_links arrives as a jsonb string (the query
    # layer's psycopg str loader — jsonb comes back as a JSON string here)
    # — parse it into a list of {name, format, url} dicts so the template
    # can render the matched resources.
    if report.get("show_api_links"):
        rows = [dict(r) for r in rows]
        for row in rows:
            row["api_links"] = json.loads(row["api_links"]) if row.get("api_links") else []

    pills = [_pill(f["label"], f["current_name"], facet_url(f["key"], "")) for f in active_facets]

    return render(
        request,
        "report.html",
        {
            "title": f"{report['label']} — data.gov.uk Explorer",
            "nav_key": "dashboard",
            "current": {
                "key": report["key"],
                "label": report["label"],
                "description": report["description"],
                "kind": report["kind"],
                "count": total,
                "hidden_cols": set(report.get("hidden_cols", [])),
                "show_api_links": report.get("show_api_links", False),
            },
            "facet_groups": facet_groups,
            "pills": pills,
            "facet_url": facet_url,
            "facet_qs": facet_qs,
            "pager_base": pager_base,
            "sort": sort,
            "dir": dir_,
            "rows": rows,
            **pagination,
        },
    )

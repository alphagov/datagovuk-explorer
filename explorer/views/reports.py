"""GET /report/{key} — one data-quality finding per page.

GET /report/{key}        — one paginated report per finding, with optional
                            single-select org facet (?org=)
GET /report/{key}?url=... — duplicate-URL detail mode (links-duplicate-urls)

The home dashboard (GET /) is views/dashboard.py; its card data is
assembled in queries/dashboard.py.
"""

import json

from django.http import Http404
from django.shortcuts import render

from explorer import facets
from explorer.queries.core import Query
from explorer.queries.reports import (
    REPORTS,
    report_facet_counts,
    report_stmts,
    report_unfiltered_count,
    report_unfiltered_options,
)

from .core import paginate

# Facet plural noun phrases — the "More …" text and, slugged (spaces →
# underscores), the ?<plural>=all expand param for each report facet key.
# Facets without an entry render fully shown (no collapse).
REPORT_FACET_PLURALS = {
    "org": "publishers",
    "api_type": "api types",
}


def _duplicate_url_report(request, report, url):
    """Duplicate-URLs detail mode (?url=<encoded-url>) — every dataset that
    links to one shared URL."""
    count_stmt = Query(report["detail_count_sql"])
    list_stmt = Query(report["detail_sql"])
    total = count_stmt.get(url)["n"]

    pagination = paginate(request, total)

    rows = list_stmt.all(url, pagination["page_size"], pagination["offset"])

    return render(
        request,
        "report.html",
        {
            "title": "Duplicate URL — data.gov.uk Explorer",
            "section": "dashboard",
            "current": {
                "key": report["key"],
                "label": report["label"],
                "description": report["description"],
                "kind": "links",
                "count": total,
                "hidden_cols": {"url"},
            },
            "detail_url": url,
            "pager_base": "",
            "rows": rows,
            **pagination,
        },
    )


def _report_facets(report, query_params, expanded) -> tuple[list, dict, list, dict]:
    """The report's facet groups + active selections for one request,
    validated against the report's own unfiltered facet options.

    Counts are self-excluding (queries/reports.py's report_facet_counts):
    each group applies the other active facets' filters, omitting its own.
    The base params are built here so the More toggles and the caller's
    facet_url/pager links share them. Returns (facet_groups,
    active_filters, active_facets, base_params)."""
    facet_groups = []
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

    # Query-string base — built before the groups so the More toggles can
    # use it. Report pages have no sort UI: sort/dir are fixed placeholders
    # and the pager base is facets + the expanded-lists extras only.
    extras = {}
    for key, plural in REPORT_FACET_PLURALS.items():
        if expanded.get(key):
            extras[plural.replace(" ", "_")] = "all"
    base_params = facets.preserve_params(
        "name",
        "asc",
        list(active_filters.items()),
        extras or None,
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
        facet_groups.append(
            facets.facet_counts_group(
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
            ),
        )
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

    # Duplicate URLs detail mode: ?url=<encoded-url>
    if report["kind"] == "duplicate-urls" and url is not None:
        return _duplicate_url_report(request, report, url)

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
            "api_type": request.GET.get("api_type"),
        },
        expanded,
    )

    # Query-string machinery — same pattern as the other facet pages: a
    # preserve_params base (report pages have no sort UI, so the pager
    # base is facets only), facet_url_for for the facet links and pills.
    facet_url = facets.facet_url_for(base_params)
    pager_base = facets.pager_base(base_params, include_sort=False)

    stmt = report_stmts(report, active_filters)
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

    return render(
        request,
        "report.html",
        {
            "title": f"{report['label']} — data.gov.uk Explorer",
            "section": "dashboard",
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
            "active_facets": active_facets,
            "facet_url": facet_url,
            "pager_base": pager_base,
            "rows": rows,
            **pagination,
        },
    )

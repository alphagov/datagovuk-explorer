"""GET /harvesters — all harvest sources (server-side sortable, facet
filters).

Facets use the same pattern as /organisations:
  ?type=...       — harvest type (ckan, gemini-csw, dcat_json, ...)
  ?active=true|false — active sources only
  ?frequency=...  — harvest frequency (MANUAL, DAILY, WEEKLY, ...)
  ?datasets=...   — dataset-count bucket (0|1-10|11-50|51-100|101-500|501-1000|1000+)
                   — same buckets as /organisations, applied to the
                   per-source dataset_count

The list is filtered/sorted/paged in SQL (one count + one page per
request); the sidebar facet counts stay Python-side over the memoised full
fetch (cheap Counters over the small list, correct self-excluding pools).

Sort columns are whitelisted in explorer.sort.HARVESTER_SORT_COLUMNS;
unknown keys fall back to the default (dataset_count desc).
"""

import json
from collections import Counter
from dataclasses import dataclass

from django.http import Http404
from django.shortcuts import render

from explorer import facets
from explorer.helpers import format_date
from explorer.queries.datasets import source_datasets_stmts
from explorer.queries.harvesters import (
    HARVEST_SOURCE,
    harvest_source_rows,
    harvest_sources_stmts,
    harvested_total,
)
from explorer.queries.organisations import (
    DATASET_BUCKET_NAMES,
    DATASET_BUCKET_TESTS,
    DATASET_BUCKETS,
    ORG,
    VALID_DATASET_BUCKETS,
)
from explorer.sort import DATASET_SORT_COLUMNS, HARVESTER_SORT_COLUMNS

from .core import _pill, _sort_dir, paginate

# Fixed value → display-label maps for the type/frequency columns and
# facets. The facet master lists are derived from the data (counts order),
# so a new type/frequency that appears in a rebuild shows up automatically.
TYPE_LABELS = {
    "ckan": "CKAN",
    "dcat_json": "DCAT JSON",
    "dcat_rdf": "DCAT RDF",
    "gemini-csw": "Gemini CSW",
    "gemini-single": "Gemini single",
    "gemini-waf": "Gemini WAF",
    "inventory": "Inventory",
}

FREQUENCY_LABELS = {
    "ALWAYS": "Always",
    "DAILY": "Daily",
    "WEEKLY": "Weekly",
    "MONTHLY": "Monthly",
    "MANUAL": "Manual",
}

ACTIVE_LABELS = {"true": "Active", "false": "Inactive"}


@dataclass(frozen=True)
class HarvesterFilters:
    """The four validated /harvesters facet selections (None = not active)."""

    type: str | None
    active: str | None
    frequency: str | None
    datasets: str | None


def _facet_master(counts: Counter, labels: dict[str, str]) -> list[tuple[str, str]]:
    """(value, label) pairs ordered by count desc (ties alphabetical) —
    the facet-group master list and the row-label lookups both consume it."""
    return [
        (value, labels.get(value, value.title())) for value, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def _dataset_bucket(count: int) -> str:
    """Bucket key for a dataset count — the orgs page's DATASET_BUCKET_TESTS
    reversed: first bucket whose range contains the count. Falls back to the
    open-ended top bucket (covers counts that drift above the defined edges)."""
    for value, test in DATASET_BUCKET_TESTS.items():
        if test(count):
            return value
    return DATASET_BUCKETS[-1][0]


def _parse_filters(request, valid_types: set, valid_frequencies: set) -> HarvesterFilters:
    """Validate the /harvesters facet selections from request.GET. Each
    facet is single-select; unknown values are ignored (falls back to no
    selection)."""
    type_ = request.GET.get("type")
    current_type = type_ if type_ in valid_types else None

    active = request.GET.get("active")
    current_active = active if active in ("true", "false") else None

    frequency = request.GET.get("frequency")
    current_frequency = frequency if frequency in valid_frequencies else None

    datasets = request.GET.get("datasets")
    current_datasets = datasets if datasets in VALID_DATASET_BUCKETS else None

    return HarvesterFilters(
        type=current_type,
        active=current_active,
        frequency=current_frequency,
        datasets=current_datasets,
    )


def _matches(r: dict, filters: HarvesterFilters, exclude: str | None = None) -> bool:
    """Row matches every active facet except `exclude` (the group being
    counted — self-excluding pools, the same rule as /organisations)."""
    return (
        (exclude == "type" or filters.type is None or r["type"] == filters.type)
        and (exclude == "active" or filters.active is None or (r["active"] is True) == (filters.active == "true"))
        and (exclude == "frequency" or filters.frequency is None or r["frequency"] == filters.frequency)
        and (
            exclude == "datasets"
            or filters.datasets is None
            or DATASET_BUCKET_TESTS[filters.datasets](r["dataset_count"])
        )
    )


def harvesters(request):
    """GET /harvesters — all harvest sources, server-side sortable, with
    type/status/frequency facets, paginated (100/page).

    The list filter/sort/page is SQL (harvest_sources_stmts — the WHERE
    clauses mirror _matches); the memoised full fetch still feeds the
    facet master lists, the validation whitelists and the Python-side
    self-excluding sidebar pools (cheap Counters over the small fetch).
    """
    rows = harvest_source_rows()

    # Facet masters over the full fetch — the validation whitelists, the
    # row-label lookups and the sidebar facet master lists all consume
    # these (computed once, not per consumer).
    all_types = Counter(r["type"] for r in rows)
    all_frequencies = Counter(r["frequency"] for r in rows)
    type_master = _facet_master(all_types, TYPE_LABELS)
    frequency_master = _facet_master(all_frequencies, FREQUENCY_LABELS)
    type_labels = dict(type_master)
    frequency_labels = dict(frequency_master)

    sort, dir_ = _sort_dir(request, HARVESTER_SORT_COLUMNS, "dataset_count", "desc")

    filters = _parse_filters(
        request,
        set(all_types),
        set(all_frequencies),
    )

    # Count + page in SQL — WHERE from the shared facet clauses, ORDER BY
    # from HARVESTER_SORT_EXPRS (see queries/harvesters.py).
    stmts = harvest_sources_stmts(
        {
            "type": filters.type,
            "active": filters.active,
            "frequency": filters.frequency,
            "datasets": filters.datasets,
        },
        sort,
        dir_,
    )
    shown_sources = stmts["count"].get(*stmts["params"])["n"]
    pagination = paginate(request, shown_sources)
    page_rows = stmts["list"].all(*stmts["params"], pagination["page_size"], pagination["offset"])

    # Decorate only the page's rows: display labels (type/frequency/
    # status) + formatted dates. The facet masters double as the label
    # maps, so rows and facets can't drift.
    for r in page_rows:
        r["type_label"] = type_labels.get(r["type"], r["type"])
        r["frequency_label"] = frequency_labels.get(r["frequency"], r["frequency"])
        r["active_label"] = ACTIVE_LABELS["true" if r["active"] else "false"]
        r["last_run"] = format_date(r["last_run"])

    # Shared query-string base: sort, dir, then the active facets in a
    # fixed order.
    base_params = facets.preserve_params(
        sort,
        dir_,
        [
            ("type", filters.type),
            ("active", filters.active),
            ("frequency", filters.frequency),
            ("datasets", filters.datasets),
        ],
    )
    facet_url = facets.facet_url_for(base_params)
    facet_qs = facets.facet_qs(base_params, include_sort=False)
    pager_base = facets.pager_base(base_params)

    # Sidebar facet groups — Python-side self-excluding pools: each group
    # counts over the rows filtered by the other facets (excluding its
    # own), via the shared core.facet_where-style _matches exclude rule.
    type_counts = Counter(r["type"] for r in rows if _matches(r, filters, exclude="type"))
    active_counts = Counter("true" if r["active"] else "false" for r in rows if _matches(r, filters, exclude="active"))
    frequency_counts = Counter(r["frequency"] for r in rows if _matches(r, filters, exclude="frequency"))
    dataset_counts = Counter(
        _dataset_bucket(r["dataset_count"]) for r in rows if _matches(r, filters, exclude="datasets")
    )

    facet_groups = {
        g["key"]: g
        for g in (
            facets.facet_counts_group(
                "type",
                "Type",
                "Filter by harvest type",
                type_master,
                type_counts,
                filters.type,
                proportions=True,
            ),
            facets.facet_counts_group(
                "active",
                "Status",
                "Filter by source status",
                [(v, ACTIVE_LABELS[v]) for v in ("true", "false")],
                active_counts,
                filters.active,
                proportions=True,
            ),
            facets.facet_counts_group(
                "frequency",
                "Frequency",
                "Filter by harvest frequency",
                frequency_master,
                frequency_counts,
                filters.frequency,
                proportions=True,
            ),
            facets.facet_counts_group(
                "datasets",
                "Datasets",
                "Filter by number of datasets",
                DATASET_BUCKETS,
                dataset_counts,
                filters.datasets,
                proportions=True,
            ),
        )
        if g is not None
    }

    pills = [
        _pill("Type", type_labels.get(filters.type, filters.type), facet_url("type", "")) if filters.type else None,
        _pill("Status", ACTIVE_LABELS[filters.active], facet_url("active", "")) if filters.active else None,
        _pill("Frequency", frequency_labels.get(filters.frequency, filters.frequency), facet_url("frequency", ""))
        if filters.frequency
        else None,
        _pill("Datasets", DATASET_BUCKET_NAMES[filters.datasets], facet_url("datasets", ""))
        if filters.datasets
        else None,
    ]

    return render(
        request,
        "harvesters.html",
        {
            "title": "Harvesters — data.gov.uk Explorer",
            "section": "orgs",
            "sources": page_rows,
            "shown_sources": shown_sources,
            **pagination,
            # Headline: harvested datasets by the dataset's own harvested
            # flag — the same definition the /datasets SOURCE facet counts.
            # The per-source dataset_count column is attribution: it only
            # covers datasets whose harvest source record is in the registry,
            # so its sum (linked_datasets) can be less.
            "total_datasets": harvested_total(),
            "linked_datasets": sum(r["dataset_count"] for r in rows),
            "sort": sort,
            "dir": dir_,
            "pills": pills,
            "facet_groups": facet_groups,
            "facet_qs": facet_qs,
            "facet_url": facet_url,
            "pager_base": pager_base,
        },
    )


def harvester(request, source_id):
    """GET /harvester/{id} — one harvest source's record and datasets.

    Follows the organisation detail pattern: the source's promoted columns
    plus the fields only the full json record carries (description,
    publisher, harvest status/jobs), then the datasets harvested by it
    (the harvest_source_id join, same as the list page).
    """
    row = HARVEST_SOURCE.get(source_id)
    if row is None:
        raise Http404

    record = json.loads(row["json"]) if row["json"] else {}
    status = record.get("status") or {}

    org_name = None
    if row["org_slug"]:
        org_row = ORG.get(row["org_slug"])
        if org_row is not None:
            org_name = org_row["display_name"] or org_row["title"] or org_row["name"]

    sort, dir_ = _sort_dir(request, DATASET_SORT_COLUMNS, "metadata_modified", "desc")

    # Count + page in SQL — one page of 100, same builder shape as
    # /organisation/{slug}.
    stmts = source_datasets_stmts(row["id"], sort, dir_)
    total = stmts["count"].get(*stmts["params"])["n"]
    pagination = paginate(request, total)
    datasets = stmts["list"].all(*stmts["params"], pagination["page_size"], pagination["offset"])

    # Pager base = sort/dir only (this page has no facets)
    pager_base = facets.pager_base({"sort": sort, "dir": dir_})

    active = bool(row["active"])
    # The API writes the literal string "None" (not null) for missing
    # timestamps — normalise it so format_date renders an em-dash.
    last_run = status.get("last_harvest_request")
    next_run = record.get("next_run")

    # The record's own publisher_title/publisher_id mirror the owning
    # organisation, so they're redundant when they match. Surface them only
    # when they differ (renames, aggregator feeds) or when no owning
    # publisher resolved.
    meta_publisher = record.get("publisher_title") or record.get("publisher_id")
    publisher = (
        None
        if org_name and meta_publisher and meta_publisher.strip().casefold() == org_name.strip().casefold()
        else meta_publisher
    )
    source = {
        "id": row["id"],
        "title": row["title"],
        "url": row["url"],
        "type_label": TYPE_LABELS.get(row["type"], (row["type"] or "").title()),
        "active": active,
        "active_label": ACTIVE_LABELS["true" if active else "false"],
        "frequency_label": FREQUENCY_LABELS.get(row["frequency"], (row["frequency"] or "").title()),
        "org_slug": row["org_slug"],
        "org_name": org_name,
        "created": format_date(row["created"]),
        "last_run": format_date(None if last_run == "None" else last_run),
        "next_run": format_date(None if next_run == "None" else next_run),
        "job_count": status.get("job_count"),
        "publisher": publisher,
        "description": record.get("description"),
        "dataset_count": total,
        "datasets": datasets,
    }

    return render(
        request,
        "harvester.html",
        {
            "title": f"{source['title'] or source['id']} — Harvesters",
            "section": "orgs",
            "source": source,
            "sort": sort,
            "dir": dir_,
            **pagination,
            "pager_base": pager_base,
        },
    )

"""GET /collections — all collections with sidebar facets."""

from dataclasses import asdict, dataclass

from django.shortcuts import render

from explorer import facets
from explorer.queries.collections import (
    COLLECTION_TOTAL,
    COLLECTIONS_SORT,
    COLLECTIONS_SORT_DEFAULT,
    collections_facet_counts,
    collections_stmts,
)
from explorer.sort import parse_sort

from .core import _pill, paginate

CATEGORY_LABELS = {
    "business-and-economy": "Business and economy",
    "early-years": "Early years",
    "environment": "Environment",
    "government-and-parliament": "Government and Parliament",
    "land-and-property": "Land and property",
    "people": "People",
    "transport": "Transport",
}


@dataclass(frozen=True)
class CollectionsFilters:
    category: str | None = None


def _parse_filters(request) -> CollectionsFilters:
    category = request.GET.get("category", "").strip() or None
    if category and category not in CATEGORY_LABELS:
        category = None
    return CollectionsFilters(category=category)


def collections(request):
    """GET /collections — the all-collections page with category sidebar."""
    filters = _parse_filters(request)
    sort, dir_ = parse_sort(request, COLLECTIONS_SORT, *COLLECTIONS_SORT_DEFAULT)

    facet_counts = collections_facet_counts(asdict(filters))

    base_params = facets.preserve_params(
        sort,
        dir_,
        [("category", filters.category)],
        defaults=COLLECTIONS_SORT_DEFAULT,
    )

    category_master = list(CATEGORY_LABELS.items())
    category_counts = {r["category"]: r["count"] for r in facet_counts["categories"]}

    facet_groups = {
        g["key"]: g
        for g in (
            facets.facet_counts_group(
                "category",
                "Category",
                "Filter by category",
                category_master,
                category_counts,
                filters.category,
            ),
        )
        if g is not None
    }

    stmts = collections_stmts(asdict(filters), sort, dir_)
    shown_count = stmts["count"].get(*stmts["params"])["n"]

    pagination = paginate(request, shown_count)
    page_collections = stmts["list"].all(
        *stmts["params"],
        pagination["page_size"],
        pagination["offset"],
    )

    base_facet_url = facets.facet_url_for(base_params)
    facet_qs = facets.facet_qs(base_params, include_sort=False)
    pager_base = facets.pager_base(base_params)

    pills = [
        _pill("Category", CATEGORY_LABELS.get(filters.category, filters.category), base_facet_url("category", ""))
        if filters.category
        else None,
    ]

    return render(
        request,
        "collections.html",
        {
            "title": "Collections — data.gov.uk Explorer",
            "nav_key": "collections",
            "collections": page_collections,
            "category_labels": CATEGORY_LABELS,
            **pagination,
            "total_collections": COLLECTION_TOTAL.get()["n"],
            "shown_collections": shown_count,
            "pills": pills,
            "sort": sort,
            "dir": dir_,
            "facet_groups": facet_groups,
            "facet_qs": facet_qs,
            "facet_url": base_facet_url,
            "pager_base": pager_base,
        },
    )

"""Search views: /search, /search/publishers, /search/datasets."""

from django.http import JsonResponse
from django.shortcuts import render

from explorer.queries.search import (
    SEARCH_PAGE_SIZE,
    count_datasets,
    count_publishers,
    search_all,
    search_datasets_page,
    search_publishers_page,
    suggest_publishers,
)

from .core import paginate


def search(request):
    q = request.GET.get("q", "").strip()
    results = search_all(q) if q else {
        "publishers": [], "publisher_count": 0,
        "datasets": [], "dataset_count": 0,
    }
    return render(request, "search.html", {
        "title": f"Search: {q}" if q else "Search",
        "section": "search",
        "narrow": True,
        "q": q,
        **results,
    })


def search_publishers(request):
    q = request.GET.get("q", "").strip()
    total = count_publishers(q) if q else 0
    paging = paginate(request, total, SEARCH_PAGE_SIZE)
    rows = search_publishers_page(q, paging["offset"]) if q else []
    return render(request, "search_publishers.html", {
        "title": f"Publishers: {q}" if q else "Publishers",
        "section": "search",
        "narrow": True,
        "q": q,
        "publishers": rows,
        "total": total,
        "pager_base": f"?q={q}",
        **paging,
    })


def publisher_suggest(request):
    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return JsonResponse([], safe=False)
    rows = suggest_publishers(q)
    return JsonResponse(
        [{"name": r["display_name"], "slug": r["slug"]} for r in rows],
        safe=False,
    )


def search_datasets(request):
    q = request.GET.get("q", "").strip()
    total = count_datasets(q) if q else 0
    paging = paginate(request, total, SEARCH_PAGE_SIZE)
    rows = search_datasets_page(q, paging["offset"]) if q else []
    return render(request, "search_datasets.html", {
        "title": f"Datasets: {q}" if q else "Datasets",
        "section": "search",
        "narrow": True,
        "q": q,
        "datasets": rows,
        "total": total,
        "pager_base": f"?q={q}",
        **paging,
    })

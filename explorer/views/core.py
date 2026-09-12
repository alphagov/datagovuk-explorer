"""Health check, 404 handler and shared view helpers."""

import math

from django.http import HttpResponse
from django.shortcuts import render

# One page size for every paginated view.
PAGE_SIZE = 100


def paginate(request, total, page_size: int = PAGE_SIZE) -> dict:
    """The standard pagination context: clamped page, total_pages, page_size,
    the LIMIT/OFFSET offset, and the 1-based "X-Y of Z" range for the
    pagination macro's count.
    """
    total_pages = max(1, math.ceil(total / page_size))
    page = min(_page_param(request), total_pages)
    offset = (page - 1) * page_size
    return {
        "page": page,
        "total_pages": total_pages,
        "page_size": page_size,
        "offset": offset,
        "start_index": offset + 1,
        "end_index": min(offset + page_size, total),
    }


def health(request):
    """Health check — Railway health checks must return 2xx."""
    return HttpResponse("ok")


def not_found(request, exception=None):
    """Custom 404 template.

    Doubles as the catch-all URL view: unrouted paths and missing static
    files hit it directly, so 404.html renders in both DEBUG modes.
    """
    return render(request, "404.html", {"title": "Page not found"}, status=404)


def _page_param(request, default: int = 1) -> int:
    """?page= as an int, clamped to >= 1. Non-ints and 0 clamp to 1;
    out-of-range pages are clamped to total_pages by paginate()."""
    try:
        page = int(request.GET.get("page", str(default)))
    except (TypeError, ValueError):
        return default
    return max(page, 1)


def _pill(label: str, value: str, href: str) -> dict:
    return {"label": label, "value": value, "href": href, "aria": f"Remove {label.lower()} filter: {value}"}


def _sort_dir(request, valid_columns, default_sort: str, default_dir: str = "asc") -> tuple[str, str]:
    """?sort=/?dir= parsed and validated against the view's column set.

    Unknown sort keys fall back to default_sort; any dir other than "desc"
    becomes "asc".
    """
    sort = request.GET.get("sort", default_sort)
    sort = sort if sort in valid_columns else default_sort
    dir_ = request.GET.get("dir", default_dir)
    dir_ = "desc" if dir_ == "desc" else "asc"
    return sort, dir_

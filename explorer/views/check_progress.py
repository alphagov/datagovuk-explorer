"""GET /check-progress — live link-check progress page.
GET /check-progress/data — JSON endpoint polled by the page.
"""

from django.http import JsonResponse
from django.shortcuts import render

from explorer.queries.check_progress import get_check_progress


def check_progress(request):
    return render(request, "check_progress.html", {"title": "Link-check progress — data.gov.uk Explorer"})


def check_progress_data(request):
    return JsonResponse(get_check_progress())

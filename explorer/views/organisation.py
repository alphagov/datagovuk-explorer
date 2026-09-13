"""GET /organisation/{slug} — publisher overview: stats, harvesters, chart."""

from datetime import UTC, datetime

from django.http import Http404
from django.shortcuts import render

from explorer.queries.datasets import (
    DATASET_COUNT,
    ORG_HARVESTED_COUNT,
    ORG_STATS,
    YEARLY_BY_ORG,
)
from explorer.queries.harvesters import HARVESTERS_BY_ORG
from explorer.queries.organisations import ORG

_CHART_START_YEAR = 2010


def _yearly_counts(rows):
    if not rows:
        return []
    counts = {r["year"]: r["count"] for r in rows}
    last = max(datetime.now(UTC).year, *[int(y) for y in counts])
    return [
        {"year": str(y), "label": str(y), "count": counts.get(str(y), 0)} for y in range(_CHART_START_YEAR, last + 1)
    ]


_TYPE_LABELS = {
    "ckan": "CKAN",
    "dcat_json": "DCAT JSON",
    "dcat_rdf": "DCAT RDF",
    "gemini-csw": "Gemini CSW",
    "gemini-single": "Gemini single",
    "gemini-waf": "Gemini WAF",
    "inventory": "Inventory",
}
_FREQUENCY_LABELS = {
    "ALWAYS": "Always",
    "DAILY": "Daily",
    "WEEKLY": "Weekly",
    "MONTHLY": "Monthly",
    "MANUAL": "Manual",
}


def organisation(request, slug):
    org_row = ORG.get(slug)
    if org_row is None:
        raise Http404

    dataset_count = DATASET_COUNT.get(slug)["count"]
    harvested_count = ORG_HARVESTED_COUNT.get(slug)["n"]
    stats = ORG_STATS.get(slug) or {}

    harvesters = HARVESTERS_BY_ORG.all(slug)
    for h in harvesters:
        h["type_label"] = _TYPE_LABELS.get(h["type"], (h["type"] or "").title())
        h["active_label"] = "Active" if h["active"] else "Inactive"
        h["frequency_label"] = _FREQUENCY_LABELS.get(h["frequency"], (h["frequency"] or "").title())

    yearly = _yearly_counts(YEARLY_BY_ORG.all(slug))
    max_yearly = max((x["count"] for x in yearly), default=0)

    return render(
        request,
        "organisation.html",
        {
            "title": org_row["display_name"] or org_row["slug"],
            "nav_key": "organisation",
            "narrow": True,
            "org": {
                "slug": org_row["slug"],
                "display_name": org_row["display_name"] or org_row["slug"],
                "state": org_row["state"],
                "approval_status": org_row["approval_status"],
                "type": org_row["type"],
                "created": org_row["created"],
                "dataset_count": dataset_count,
                "harvested_count": harvested_count,
                "manual_count": dataset_count - harvested_count,
                "total_resources": stats.get("total_resources") or 0,
                "total_views": stats.get("total_views") or 0,
                "last_published": stats.get("last_published"),
            },
            "harvesters": harvesters,
            "yearly": yearly,
            "max_yearly": max_yearly,
        },
    )

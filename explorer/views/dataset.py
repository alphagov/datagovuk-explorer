"""GET /dataset/{orgSlug}/{datasetId} — single dataset detail.

Full CKAN JSON from dataset_json, a sortable resources table, temporal
coverage, harvest status, related datasets (pgvector embeddings),
series membership, and the LLM review (from reviews table) and
classification (from suggestions table) — DB-backed, latest per dataset,
ok:true only.
"""

import json

from django.http import Http404
from django.shortcuts import render

from explorer.queries.datasets import (
    DATASET_JSON,
    DATASET_TEMPORAL_PERIODS,
)
from explorer.queries.embeddings import BAKED_SEMANTIC_RELATED
from explorer.queries.harvesters import HARVEST_SOURCE
from explorer.queries.organisations import ORG
from explorer.queries.reviews import get_review
from explorer.queries.series import DATASET_SERIES, SERIES_DATASETS_EXCEPT
from explorer.queries.suggestions import get_classification
from explorer.sort import RESOURCE_SORT_COLUMNS, parse_sort, sort_resources


def _fmt_temporal(v):
    """CKAN stores temporal coverage as a plain string or an array of dates
    (multiple coverage periods); join arrays so the template just renders
    text. None for blank values."""
    if v is None or v == "":
        return None
    if isinstance(v, list):
        return ", ".join(v) if v else None
    return str(v)


def dataset(request, org_slug, dataset_id):
    """GET /dataset/{orgSlug}/{datasetId} — one dataset's detail page."""
    json_row = DATASET_JSON.get(dataset_id)
    org_row = ORG.get(org_slug)
    if json_row is None:
        raise Http404

    dataset_pk = json_row["dataset_pk"]
    dataset = json.loads(json_row["json"])

    org = {
        "slug": org_slug,
        "display_name": (
            (org_row["display_name"] if org_row else None)
            or (dataset.get("_organisation") or {}).get("display_name")
            or org_slug
        ),
    }

    # Temporal coverage — declared From/To/Granularity render from the raw
    # JSON; when the publisher declared none, periods inferred from the
    # title/resource names render as a separate suggested section.
    temporal = {
        "from": _fmt_temporal(dataset.get("temporal_coverage-from")),
        "to": _fmt_temporal(dataset.get("temporal_coverage-to")),
        "granularity": _fmt_temporal(dataset.get("temporal_granularity")),
    }
    suggested = [
        {"from": r["from_year"], "to": r["to_year"], "source": r["source"]}
        for r in DATASET_TEMPORAL_PERIODS.all(dataset_pk)
        if r["source"] != "declared"
    ]

    # Harvest status — read from the full JSON so the detail page doesn't
    # depend on the summary row
    extras = {e["key"]: e["value"] for e in dataset.get("extras") or []}
    harvested = bool(extras.get("harvest_object_id"))
    source_id = extras.get("harvest_source_id") or None
    source_title = extras.get("harvest_source_title") or None
    # The harvest_source_id only links when the source's record is still in
    # the registry — CKAN can drop source rows while the datasets citing
    # them remain, and /harvester/{id} 404s for those.
    source_row = HARVEST_SOURCE.get(source_id) if source_id else None
    harvest_source = None
    if source_title or source_row:
        harvest_source = {
            # None (no link) when the source record is gone from the registry
            "id": source_id if source_row else None,
            "title": source_title or (source_row["title"] if source_row else None) or source_id,
        }

    # Resources default to natural (position) order
    sort, dir_ = parse_sort(request, RESOURCE_SORT_COLUMNS, "position")
    if dataset.get("resources"):
        sort_resources(dataset["resources"], sort, dir_)

    # Semantic related — pre-baked at build time
    semantic_related = BAKED_SEMANTIC_RELATED.all(dataset_pk)

    # Series membership
    series = None
    series_datasets: list = []
    series_rows = DATASET_SERIES.all(dataset_pk)
    if series_rows:
        series = series_rows[0]
        series_datasets = SERIES_DATASETS_EXCEPT.all(series["id"], dataset_pk)

    return render(
        request,
        "dataset.html",
        {
            "title": f"{dataset.get('title') or dataset.get('name')} — {org['display_name']}",
            "nav_key": "dataset",
            "narrow": True,
            "org": org,
            "dataset": dataset,
            "temporal": temporal,
            "suggested": suggested,
            "harvested": harvested,
            "harvest_source": harvest_source,
            "sort": sort,
            "dir": dir_,
            "review": get_review(dataset_pk),
            "classification": get_classification(dataset_pk),
            "semantic_related": semantic_related,
            "series": series,
            "series_datasets": series_datasets,
        },
    )

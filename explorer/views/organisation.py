"""GET /organisation/{slug} — datasets for one organisation, paginated
100/page (SQL LIMIT/OFFSET).

Sortable via ?sort= (DATASET_SORT_COLUMNS whitelist) and ?dir=asc|desc.
Default: metadata_modified desc (most recently updated first). A prior
app's comment stated this intent but its code
(`dir === 'desc' ? 'desc' : 'asc'`) actually defaulted to asc (oldest
first); we follow the stated intent.
"""

from django.http import Http404
from django.shortcuts import render

from explorer import facets
from explorer.helpers import yearly_counts
from explorer.queries.datasets import (
    DATASET_COUNT,
    ORG_HARVESTED_COUNT,
    YEARLY_BY_ORG,
    org_datasets_stmts,
)
from explorer.queries.organisations import ORG
from explorer.sort import DATASET_SORT_COLUMNS

from .core import _sort_dir, paginate


def organisation(request, slug):
    """GET /organisation/{slug} — one org's datasets, sorted by ?sort/?dir.

    Count + page come from the SQL builder (org_datasets_stmts) — the page
    used to fetch every dataset row and sort in Python (up to 5.6k rows for
    the largest orgs); now it fetches one page of 100 (pagination-plan
    workstream E).
    """
    org_row = ORG.get(slug)
    if org_row is None:
        raise Http404

    sort, dir_ = _sort_dir(request, DATASET_SORT_COLUMNS, "metadata_modified", "desc")

    stmts = org_datasets_stmts(slug, sort, dir_)
    total = stmts["count"].get(*stmts["params"])["n"]
    pagination = paginate(request, total)
    datasets = stmts["list"].all(*stmts["params"], pagination["page_size"], pagination["offset"])

    # Pager base = sort/dir only (this page has no facets)
    pager_base = facets.pager_base({"sort": sort, "dir": dir_})

    org = {
        "slug": org_row["slug"],
        "display_name": org_row["display_name"] or org_row["slug"],
        "dataset_count": DATASET_COUNT.get(slug)["count"],
        "harvested_count": ORG_HARVESTED_COUNT.get(slug)["n"],
        "datasets": datasets,
    }

    # Datasets created per year for this org's chart
    yearly = yearly_counts(YEARLY_BY_ORG.all(slug))
    max_yearly = max((x["count"] for x in yearly), default=0)

    return render(
        request,
        "organisation.html",
        {
            "title": f"{org['display_name']} — Datasets",
            "section": "orgs",
            "org": org,
            "sort": sort,
            "dir": dir_,
            "yearly": yearly,
            "max_yearly": max_yearly,
            **pagination,
            "pager_base": pager_base,
        },
    )

"""GET /dataset/{orgSlug}/{datasetId} — single dataset detail.

Full CKAN JSON from dataset_json, a sortable resources table, temporal
coverage, harvest status, related datasets (FTS + pgvector embeddings),
series membership, and the LLM review/classification from the reviews
table (explorer/queries — DB-backed: latest per dataset, ok:true only).
"""

import json
import re

from django.http import Http404
from django.shortcuts import render

from explorer.queries.datasets import (
    DATASET_JSON,
    DATASET_TEMPORAL_PERIODS,
    RELATED_BY_FTS,
)
from explorer.queries.embeddings import EMBEDDING_TEXT, SEMANTIC_RELATED
from explorer.queries.harvesters import HARVEST_SOURCE
from explorer.queries.organisations import ORG
from explorer.queries.reviews import get_classification, get_review
from explorer.queries.series import DATASET_SERIES, SERIES_DATASETS_EXCEPT
from explorer.sort import RESOURCE_SORT_COLUMNS, sort_resources

from .core import _sort_dir

# Common English stopwords, plus CKAN boilerplate terms that pollute the
# match string with noise ("data", "dataset", "open", etc.).
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "shall",
        "you",
        "your",
        "we",
        "our",
        "they",
        "their",
        "its",
        "it",
        "this",
        "that",
        "these",
        "those",
        "not",
        "no",
        "nor",
        "so",
        "as",
        "if",
        "then",
        "than",
        "too",
        "very",
        "just",
        "about",
        "also",
        "into",
        "over",
        "under",
        "such",
        "only",
        "other",
        "new",
        "some",
        "each",
        "all",
        "both",
        "few",
        "more",
        "most",
        "any",
        "up",
        "out",
        "when",
        "where",
        "how",
        "which",
        "who",
        "what",
        "whom",
        "here",
        "there",
        "after",
        "before",
        "between",
        "data",
        "dataset",
        "datasets",
        "open",
        "access",
        "information",
        "publish",
        "published",
        "publishing",
        "available",
        "download",
        "file",
        "files",
        "format",
        "link",
        "links",
        "page",
        "site",
        "web",
    ],
)

# Websearch terms — single words shorter than this are noise.
MIN_WORD_LENGTH = 3


def build_match_string(title: str | None, tags: list | None) -> str | None:
    """Build a websearch match string from a dataset's title and tags.

    Format ("term" OR "term") is compatible with PostgreSQL's
    websearch_to_tsquery function.
    """
    # Title words — keep unique words of 3+ chars that aren't stopwords
    title_words = re.sub(r"[^a-z0-9\s]", " ", (title or "").lower()).split()
    terms = [w for w in title_words if len(w) >= MIN_WORD_LENGTH and w not in STOPWORDS]

    # Tag names — always include (they're structured, high-signal)
    for t in tags or []:
        name = re.sub(
            r"\s+",
            " ",
            (t.get("display_name") or t.get("name") or "").lower(),
        ).strip()
        if name:
            terms.append(name)

    # Deduplicate (keeping insertion order), then wrap each term in double
    # quotes and OR them together (compatible with websearch_to_tsquery).
    unique = list(dict.fromkeys(terms))
    if not unique:
        return None
    return " OR ".join(f'"{t}"' for t in unique)


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
        for r in DATASET_TEMPORAL_PERIODS.all(dataset_id)
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
    sort, dir_ = _sort_dir(request, RESOURCE_SORT_COLUMNS, "position")
    if dataset.get("resources"):
        sort_resources(dataset["resources"], sort, dir_)

    # Related datasets via tsvector "more like this"
    match_str = build_match_string(dataset.get("title"), dataset.get("tags"))
    # Small list — bounded by LIMIT 20 in SQL, no pager needed.
    related: list = []
    if match_str:
        # Excludes datasets in the same detected series as the current one
        related = RELATED_BY_FTS.all(match_str, dataset["id"], dataset["id"])

    # Related datasets via semantic embeddings (pgvector KNN)
    semantic_related: list = []
    emb_row = EMBEDDING_TEXT.get(dataset["id"])
    if emb_row:
        semantic_related = SEMANTIC_RELATED.all(
            emb_row["vector_text"],
            dataset["id"],
            dataset["id"],
        )

    # Series membership
    series = None
    series_datasets: list = []
    series_rows = DATASET_SERIES.all(dataset["id"])
    if series_rows:
        series = series_rows[0]
        series_datasets = SERIES_DATASETS_EXCEPT.all(series["id"], dataset["id"])

    return render(
        request,
        "dataset.html",
        {
            "title": f"{dataset.get('title') or dataset.get('name')} — {org['display_name']}",
            "section": "datasets",
            "narrow": True,
            "org": org,
            "dataset": dataset,
            "temporal": temporal,
            "suggested": suggested,
            "harvested": harvested,
            "harvest_source": harvest_source,
            "sort": sort,
            "dir": dir_,
            "review": get_review(dataset_id),
            "classification": get_classification(dataset_id),
            "related": related,
            "semantic_related": semantic_related,
            "series": series,
            "series_datasets": series_datasets,
        },
    )

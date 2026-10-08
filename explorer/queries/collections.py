"""/collections query builder — count/list statements compiled per
(filters, sort, dir)."""

from explorer.sort import order_by

from .core import Query, cached_unfiltered, facet_where

# L2 distance below which a collection's neighbour counts as "related" —
# gates the collection detail page's related list. Must match
# scripts/build_related.py::RELATED_DISTANCE_THRESHOLD (which bakes the counts
# this list page shows): 0.83 is tuned to EmbeddingGemma-300M, the model that
# replaced BGE (whose equivalent was 0.77).
RELATED_DISTANCE_THRESHOLD = 0.83

COLLECTIONS_SORT = {
    "title": "LOWER(COALESCE(c.title, ''))",
    "collection": "LOWER(c.collection)",
    "views": "COALESCE(c.views, 0)",
    "page_last_updated": "c.page_last_updated",
    "related": "COALESCE(c.related_count, 0)",
}

COLLECTIONS_SORT_DEFAULT = ("views", "desc")

# page_last_updated is a nullable real date — missing values sort last like
# the other date columns (see sort.order_by).
COLLECTIONS_NULLS_LAST = frozenset({"page_last_updated"})

COLLECTION_TOTAL = Query("SELECT COUNT(*) AS n FROM collection_pages")

COLLECTION_DETAIL = Query(
    "SELECT slug, collection, title, description,"
    " websites, api, dataset, page_last_updated, views, status"
    " FROM collection_pages WHERE slug = %s",
)


def _collection_clause(filters: dict, exclude: str | None = None) -> tuple[list, list]:
    if exclude == "collection" or not filters.get("collection"):
        return [], []
    return ["c.collection = %s"], [filters["collection"]]


_FACET_CLAUSES = {
    "collection": _collection_clause,
}


def _facet_where(filters: dict, exclude: str | None = None) -> tuple[str, list]:
    return facet_where(_FACET_CLAUSES, filters, exclude)


def collections_stmts(filters: dict, sort: str, dir_: str) -> dict:
    """Return { count, list, params } for one (filters, sort, dir) combo."""
    where, params = _facet_where(filters)
    order_sql = order_by(COLLECTIONS_SORT, sort, dir_, "c.slug", nulls_last=COLLECTIONS_NULLS_LAST)

    return {
        "params": params,
        "count": Query(f"SELECT COUNT(*) AS n FROM collection_pages c{where}"),
        "list": Query(
            "SELECT c.slug, c.collection, c.title,"
            "  c.page_last_updated, c.views, c.related_count AS related"
            " FROM collection_pages c"
            f"{where}"
            f" ORDER BY {order_sql}"
            " LIMIT %s OFFSET %s",
        ),
    }


# Pre-baked collection related datasets — trivial indexed lookup replacing
# the live COLLECTION_RELATED_DATASETS query at request time.
BAKED_COLLECTION_RELATED = Query(
    """SELECT d.ckan_id, d.title, d.org_slug, d.org_display_name,
              d.theme_primary, d.metadata_modified, r.distance
       FROM collection_related_datasets r
       JOIN datasets d ON d.id = r.dataset_id
       WHERE r.slug = %s
       ORDER BY r.rank""",
)

# Kept for use at build time (scripts/build_related.py).
COLLECTION_EMBEDDING = Query(
    "SELECT embedding::text AS embedding FROM collection_embeddings WHERE slug = %s",
)

COLLECTION_RELATED_DATASETS = Query(
    """SELECT d.ckan_id, d.title, d.org_slug, d.org_display_name, d.theme_primary,
              d.metadata_modified,
              emb.embedding <-> %s::vector AS distance
       FROM dataset_embeddings emb
       JOIN embedding_map m ON m.rowid = emb.rowid
       JOIN datasets d ON d.id = m.dataset_id
       WHERE d.resource_count > 0
       ORDER BY distance, d.id
       LIMIT 12""",
)


@cached_unfiltered
def collections_facet_counts(filters: dict) -> dict:
    """Collection facet counts with self-exclusion."""
    col_where, col_params = _facet_where(filters, exclude="collection")

    collections = Query(
        f"SELECT c.collection, COUNT(*) AS count"
        f" FROM collection_pages c{col_where}"
        " GROUP BY c.collection ORDER BY c.collection",
    ).all(*col_params)

    return {"collections": collections}

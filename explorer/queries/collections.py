"""/collections query builder — count/list statements compiled per
(filters, sort, dir)."""

from explorer.sort import order_by

from .core import Query, cached_unfiltered, facet_where

RELATED_DISTANCE_THRESHOLD = 0.77

COLLECTIONS_SORT = {
    "title": "LOWER(COALESCE(c.title, ''))",
    "collection": "LOWER(c.collection)",
    "views": "COALESCE(c.views, 0)",
    "page_last_updated": "COALESCE(c.page_last_updated, '')",
    "related": "COALESCE(related.count, 0)",
}

COLLECTIONS_SORT_DEFAULT = ("views", "desc")

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


_OVER_THRESHOLD_JOIN = (
    " LEFT JOIN LATERAL ("
    f"  SELECT 12 - COUNT(*) FILTER (WHERE sub.distance > {RELATED_DISTANCE_THRESHOLD}) AS count"
    "  FROM ("
    "    SELECT emb.embedding <-> ce.embedding AS distance"
    "    FROM dataset_embeddings emb"
    "    JOIN embedding_map m ON m.rowid = emb.rowid"
    "    JOIN datasets d ON d.id = m.dataset_id"
    "    WHERE d.resource_count > 0"
    "    ORDER BY emb.embedding <-> ce.embedding, d.id"
    "    LIMIT 12"
    "  ) sub"
    " ) related ON true"
)


def collections_stmts(filters: dict, sort: str, dir_: str) -> dict:
    """Return { count, list, params } for one (filters, sort, dir) combo."""
    where, params = _facet_where(filters)
    order_sql = order_by(COLLECTIONS_SORT, sort, dir_, "c.slug")

    return {
        "params": params,
        "count": Query(f"SELECT COUNT(*) AS n FROM collection_pages c{where}"),
        "list": Query(
            "SELECT c.slug, c.collection, c.title,"
            "  c.page_last_updated, c.views, related.count AS related"
            " FROM collection_pages c"
            " LEFT JOIN collection_embeddings ce ON ce.slug = c.slug"
            f"{_OVER_THRESHOLD_JOIN}"
            f"{where}"
            f" ORDER BY {order_sql}"
            " LIMIT %s OFFSET %s",
        ),
    }


COLLECTION_EMBEDDING = Query(
    "SELECT embedding::text AS embedding FROM collection_embeddings WHERE slug = %s",
)

COLLECTION_RELATED_DATASETS = Query(
    """SELECT d.id, d.title, d.org_slug, d.org_display_name, d.theme_primary,
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

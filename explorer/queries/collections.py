"""/collections query builder — count/list statements compiled per
(filters, sort, dir)."""

from explorer.sort import order_by

from .core import Query, cached_unfiltered, facet_where

COLLECTIONS_SORT = {
    "title": "LOWER(COALESCE(c.title, ''))",
    "category": "LOWER(c.category)",
    "views": "COALESCE(c.views, 0)",
    "page_last_updated": "COALESCE(c.page_last_updated, '')",
}

COLLECTIONS_SORT_DEFAULT = ("views", "desc")

COLLECTION_TOTAL = Query("SELECT COUNT(*) AS n FROM collections")

COLLECTION_DETAIL = Query(
    "SELECT slug, category, title, description,"
    " websites, api, dataset, page_last_updated, views, status"
    " FROM collections WHERE slug = %s",
)


def _category_clause(filters: dict, exclude: str | None = None) -> tuple[list, list]:
    if exclude == "category" or not filters.get("category"):
        return [], []
    return ["c.category = %s"], [filters["category"]]


_FACET_CLAUSES = {
    "category": _category_clause,
}


def _facet_where(filters: dict, exclude: str | None = None) -> tuple[str, list]:
    return facet_where(_FACET_CLAUSES, filters, exclude)


def collections_stmts(filters: dict, sort: str, dir_: str) -> dict:
    """Return { count, list, params } for one (filters, sort, dir) combo."""
    where, params = _facet_where(filters)
    order_sql = order_by(COLLECTIONS_SORT, sort, dir_, "c.slug")

    return {
        "params": params,
        "count": Query(f"SELECT COUNT(*) AS n FROM collections c{where}"),
        "list": Query(
            "SELECT c.slug, c.category, c.title,"
            "  c.page_last_updated, c.views"
            f" FROM collections c{where}"
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
    """Category facet counts with self-exclusion."""
    cat_where, cat_params = _facet_where(filters, exclude="category")

    categories = Query(
        f"SELECT c.category, COUNT(*) AS count FROM collections c{cat_where} GROUP BY c.category ORDER BY c.category",
    ).all(*cat_params)

    return {"categories": categories}

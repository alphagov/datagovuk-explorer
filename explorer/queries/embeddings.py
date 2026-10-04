"""Embedding statements — pgvector semantic search and the dataset's own
embedding probe behind the dataset detail page's "semantically related"
list."""

from .core import Query

# Pre-baked semantic related datasets — trivial indexed lookup replacing the
# live SEMANTIC_RELATED query at request time.
BAKED_SEMANTIC_RELATED = Query(
    """SELECT d.ckan_id, d.title, d.org_slug, d.org_display_name,
              d.theme_primary, d.metadata_modified, r.score AS distance
       FROM related_datasets r
       JOIN datasets d ON d.id = r.related_id
       WHERE r.dataset_id = %s
       ORDER BY r.rank""",
)

# The dataset's own embedding as a pgvector literal, used as the probe for
# SEMANTIC_RELATED. Kept for use at build time (scripts/build_related.py).
EMBEDDING_LITERAL = Query(
    "SELECT e.embedding::text AS embedding "
    "FROM embedding_map m "
    "JOIN dataset_embeddings e ON e.rowid = m.rowid "
    "WHERE m.dataset_id = %s",
)

# Semantic "more like this" via pgvector KNN. The series exclusion (the
# NOT IN block) matches RELATED_BY_FTS: datasets in the same detected
# series as the current one are not "related".
#
# Served by the HNSW index on dataset_embeddings.embedding (migration
# 0012) — approximate, with hnsw.ef_search (settings.py) trading recall
# for latency. Before the index this was an exact scan over every vector
# (~400ms); the index drops it to single-digit milliseconds.
SEMANTIC_RELATED = Query(
    """SELECT d.ckan_id, d.title, d.org_slug, d.org_display_name, d.theme_primary,
              d.metadata_modified,
              emb.embedding <-> %s::vector AS distance
       FROM dataset_embeddings emb
       JOIN embedding_map m ON m.rowid = emb.rowid
       JOIN datasets d ON d.id = m.dataset_id
       WHERE m.dataset_id != %s
         AND d.id NOT IN (
           SELECT sd.dataset_id FROM series_datasets sd
           WHERE sd.series_id IN (
             SELECT sd2.series_id FROM series_datasets sd2 WHERE sd2.dataset_id = %s
           )
         )
       ORDER BY distance, d.id
       LIMIT 20""",
)

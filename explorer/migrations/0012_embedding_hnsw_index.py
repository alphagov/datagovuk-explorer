"""ANN index for pgvector semantic "more like this" — the /dataset/{org}/
{id} page's related-datasets list, plus the embedding_map lookup index.

SEMANTIC_RELATED (explorer/queries/embeddings.py) orders every dataset by
`embedding <-> probe` to find the nearest 20. With no index on the vector
column that's an exact scan over all vectors — measured ~800ms cold /
~370-410ms warm on the 66k-row baseline, dominating the page (409ms of a
601ms request). An HNSW index (operator class vector_l2_ops, matching the
query's `<->` operator) makes it an approximate neighbour search:
single-digit milliseconds in testing (the page as a whole went 601ms ->
~100ms, the rest being the FTS related list + template overhead).

HNSW is approximate, so a few of the true top-20 can be missed. The
recall/latency dial is `hnsw.ef_search`, set per connection in
config/settings.py (measured on the 66k baseline: pgvector's default 40
≈ 58% recall@20, 200 ≈ 85%, 400 ≈ 95%, at ~2/4/8ms per query). The
connection default is 400.

Created here rather than by the build pipeline, per the "migrations own the
schema" rule (see 0003): on a fresh DB migrate runs before the load, so the
build's embedding inserts maintain the index, and a rebuild's TRUNCATE
resets it. One accepted cost: migrate on an already-populated DB builds the
graph in place (~5 min at the default maintenance_work_mem — raise that GUC
for the session to speed it up).

idx_embedding_map_dataset is a plain btree for the dataset -> embedding
lookup (EMBEDDING_TEXT) and the ANN query's join through embedding_map.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        # dataset_embeddings.embedding (vector) comes from 0002.
        ("explorer", "0011_dataset_api"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS idx_dataset_embeddings_hnsw "
                "ON dataset_embeddings USING hnsw (embedding vector_l2_ops)"
            ),
            reverse_sql="DROP INDEX IF EXISTS idx_dataset_embeddings_hnsw",
        ),
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_embedding_map_dataset ON embedding_map (dataset_id)",
            reverse_sql="DROP INDEX IF EXISTS idx_embedding_map_dataset",
        ),
    ]

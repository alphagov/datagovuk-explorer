"""Drop embedding_map.vector_text — the pre-pgvector duplicate of the
embedding.

0001 stored the embedding only as JSON text here; 0002 added the real
vector(768) column to dataset_embeddings. Both were then written on every
embedding run, but the app used vector_text only to hand a pgvector literal
to SEMANTIC_RELATED. That literal is now derived from
dataset_embeddings.embedding (EMBEDDING_LITERAL), so the text copy is dead
weight: it is the largest object in the database (~780MB on disk, ~57% of
the data-only dump), while the binary column it duplicated is the one the
HNSW index needs.

embedding_map itself stays — it is still the dataset id -> rowid map.
Reversing re-adds a NOT NULL column with no default, so it only works on an
empty table; the project's restore path drops the schema and replays a dump
rather than reversing migrations.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0013_drop_dataset_json_gin"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="embeddingmap",
            name="vector_text",
        ),
    ]

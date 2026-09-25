"""Add collection_embeddings — pre-computed vectors for collection pages,
used as KNN probes against the dataset_embeddings HNSW index."""

from django.db import migrations

_CREATE = """\
CREATE TABLE collection_embeddings (
    slug        TEXT PRIMARY KEY REFERENCES collections(slug) ON DELETE CASCADE,
    embedding   vector(768) NOT NULL
);
"""

_DROP = "DROP TABLE IF EXISTS collection_embeddings;"


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0017_collections"),
    ]

    operations = [
        migrations.RunSQL(_CREATE, _DROP),
    ]

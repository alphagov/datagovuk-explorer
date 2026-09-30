"""Covering index on datasets(id) INCLUDE (org_slug, org_display_name, title).

The /reviews list and publisher-facet queries join reviews _DEDUP to datasets
for title/org_slug/org_display_name. Without this index Postgres does a seq
scan over the full datasets table (~128MB including fts/notes), then a Hash
Join. With it the join becomes an index-only scan on a narrow index.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0007_idx_reviews_covering"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="dataset",
            index=models.Index(
                fields=["id"],
                include=["org_slug", "org_display_name", "title"],
                name="idx_datasets_reviews_cover",
            ),
        ),
    ]

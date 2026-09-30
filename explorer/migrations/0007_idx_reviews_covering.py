"""Extend idx_reviews_dataset_id_desc to include findability and resources.

The _DEDUP subquery (queries/reviews.py, queries/organisations.py) selects
dataset_id, id, findability, resources from reviews WHERE ok = true. The
existing partial index covers (dataset_id, id DESC) but not findability or
resources, forcing a heap fetch per row. Adding them as INCLUDE columns
allows index-only scans for the dedup.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0006_idx_datasets_views_desc"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="review",
            name="idx_reviews_dataset_id_desc",
        ),
        migrations.AddIndex(
            model_name="review",
            index=models.Index(
                fields=["dataset", "-id"],
                include=["findability", "resources"],
                name="idx_reviews_dataset_id_desc",
                condition=models.Q(ok=True),
            ),
        ),
    ]

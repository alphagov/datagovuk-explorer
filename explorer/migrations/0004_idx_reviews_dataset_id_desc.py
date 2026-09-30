"""Add composite partial index on reviews(dataset_id, id DESC) WHERE ok = true.

Speeds up the DISTINCT ON (dataset_id) ORDER BY dataset_id, id DESC query used
by _REVIEW_DEDUP in queries/organisations.py and queries/reviews.py.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0003_split_review_suggestion"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="review",
            index=models.Index(
                fields=["dataset", "-id"],
                name="idx_reviews_dataset_id_desc",
                condition=models.Q(ok=True),
            ),
        ),
    ]

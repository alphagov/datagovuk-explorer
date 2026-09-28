"""Split the reviews table: move suggestion columns into a new suggestions table."""

import django.db.models.deletion
from django.db import migrations, models


def copy_suggestions(apps, schema_editor):
    """Copy suggestion data from reviews into the new suggestions table."""
    schema_editor.execute(
        "INSERT INTO suggestions (dataset_id, ok, theme, theme_confidence,"
        '  tags, title, "desc", created_at, json)'
        " SELECT dataset_id, ok, theme, theme_confidence,"
        '  tags, title, "desc", created_at, json'
        " FROM reviews",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0002_drop_review_overall_metadata"),
    ]

    operations = [
        migrations.CreateModel(
            name="Suggestion",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("ok", models.BooleanField(db_default=True)),
                ("theme", models.TextField(blank=True, null=True)),
                ("theme_confidence", models.TextField(blank=True, null=True)),
                ("tags", models.TextField(blank=True, null=True)),
                ("title", models.TextField(blank=True, null=True)),
                ("desc", models.TextField(blank=True, null=True)),
                ("created_at", models.TextField(blank=True, null=True)),
                ("json", models.TextField()),
                (
                    "dataset",
                    models.ForeignKey(
                        db_column="dataset_id",
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="explorer.dataset",
                    ),
                ),
            ],
            options={
                "db_table": "suggestions",
            },
        ),
        migrations.AddIndex(
            model_name="suggestion",
            index=models.Index(fields=["dataset"], name="idx_suggestions_dataset"),
        ),
        migrations.RunPython(copy_suggestions, migrations.RunPython.noop),
        migrations.RemoveField(model_name="review", name="theme"),
        migrations.RemoveField(model_name="review", name="theme_confidence"),
        migrations.RemoveField(model_name="review", name="tags"),
        migrations.RemoveField(model_name="review", name="title"),
        migrations.RemoveField(model_name="review", name="desc"),
    ]

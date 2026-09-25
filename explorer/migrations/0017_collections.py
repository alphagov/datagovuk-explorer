"""Add the collections table — curated topic pages with Search Console views."""

from django.db import migrations, models

_CREATE = """\
CREATE TABLE collections (
    slug                TEXT PRIMARY KEY,
    category            TEXT NOT NULL,
    title               TEXT NOT NULL,
    description         TEXT,
    websites            JSONB,
    api                 JSONB,
    dataset             JSONB,
    page_last_updated   TEXT,
    visualisation_data  TEXT,
    status              TEXT,
    views               INTEGER NOT NULL DEFAULT 0
);
"""

_DROP = "DROP TABLE IF EXISTS collections;"


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0016_link_check_results"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(_CREATE, _DROP)],
            state_operations=[
                migrations.CreateModel(
                    name="Collection",
                    fields=[
                        (
                            "slug",
                            models.TextField(primary_key=True, serialize=False),
                        ),
                        ("category", models.TextField()),
                        ("title", models.TextField()),
                        ("description", models.TextField(blank=True, null=True)),
                        ("websites", models.JSONField(blank=True, null=True)),
                        ("api", models.JSONField(blank=True, null=True)),
                        ("dataset", models.JSONField(blank=True, null=True)),
                        ("page_last_updated", models.TextField(blank=True, null=True)),
                        ("visualisation_data", models.TextField(blank=True, null=True)),
                        ("status", models.TextField(blank=True, null=True)),
                        ("views", models.IntegerField(db_default=0)),
                    ],
                    options={
                        "db_table": "collections",
                    },
                ),
            ],
        ),
    ]

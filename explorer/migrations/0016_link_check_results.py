"""Replace link_errors with url-keyed link_check_results.

Drops the old link_errors table (superseded by the link checker writing
directly to link_check_results, keyed on URL) and creates the new
url-keyed link_check_results table — one row per unique URL instead of
one row per resource.
"""

from django.db import migrations, models

_CREATE = """\
CREATE TABLE link_check_results (
    url         TEXT PRIMARY KEY,
    checked_at  TEXT,
    method      TEXT,
    ok          BOOLEAN,
    http_status INTEGER,
    final_url   TEXT,
    error       TEXT
);
"""

_DROP = "DROP TABLE IF EXISTS link_check_results;"


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0015_dataset_content_hash"),
    ]

    operations = [
        migrations.DeleteModel(name="LinkError"),
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(_CREATE, _DROP)],
            state_operations=[
                migrations.CreateModel(
                    name="LinkCheckResult",
                    fields=[
                        (
                            "url",
                            models.TextField(primary_key=True, serialize=False),
                        ),
                        ("checked_at", models.TextField(blank=True, null=True)),
                        ("method", models.TextField(blank=True, null=True)),
                        ("ok", models.BooleanField(blank=True, null=True)),
                        ("http_status", models.IntegerField(blank=True, null=True)),
                        ("final_url", models.TextField(blank=True, null=True)),
                        ("error", models.TextField(blank=True, null=True)),
                    ],
                    options={
                        "db_table": "link_check_results",
                    },
                ),
            ],
        ),
    ]

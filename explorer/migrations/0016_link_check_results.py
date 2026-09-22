from django.db import migrations, models

_UP = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'link_check_results' AND column_name = 'link_id'
    ) THEN
        -- Upgrade from link_id-keyed table: keep the most recent result per URL.
        CREATE TABLE link_check_results_new (
            url         TEXT PRIMARY KEY,
            checked_at  TEXT,
            method      TEXT,
            ok          BOOLEAN,
            http_status INTEGER,
            final_url   TEXT,
            error       TEXT
        );
        INSERT INTO link_check_results_new
            (url, checked_at, method, ok, http_status, final_url, error)
        SELECT DISTINCT ON (url)
            url, checked_at, method, ok, http_status, final_url, error
        FROM link_check_results
        WHERE url IS NOT NULL AND url != ''
        ORDER BY url, checked_at DESC NULLS LAST;
        DROP TABLE link_check_results;
        ALTER TABLE link_check_results_new RENAME TO link_check_results;
    ELSIF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'link_check_results'
    ) THEN
        -- Fresh install.
        CREATE TABLE link_check_results (
            url         TEXT PRIMARY KEY,
            checked_at  TEXT,
            method      TEXT,
            ok          BOOLEAN,
            http_status INTEGER,
            final_url   TEXT,
            error       TEXT
        );
    END IF;
END $$;
"""

_DOWN = """
DROP TABLE IF EXISTS link_check_results;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0015_dataset_content_hash"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(_UP, _DOWN)],
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

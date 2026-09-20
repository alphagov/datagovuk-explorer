import django.db.models.deletion
from django.db import migrations, models

# When upgrading from the old url-keyed schema, migrate existing check results
# by joining link_check_results on url back to links, taking one result per
# link (DISTINCT ON l.id) so shared-URL links each get their own row.
_UP = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'link_check_results' AND column_name = 'link_id'
    ) THEN
        IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'link_check_results'
        ) THEN
            -- Upgrade: old url-keyed table exists — save, recreate, repopulate.
            CREATE TABLE link_check_results_old AS SELECT * FROM link_check_results;
            DROP TABLE link_check_results;
            CREATE TABLE link_check_results (
                link_id     INTEGER PRIMARY KEY REFERENCES links(id) ON DELETE CASCADE,
                url         TEXT,
                checked_at  TEXT,
                method      TEXT,
                ok          BOOLEAN,
                http_status INTEGER,
                final_url   TEXT,
                error       TEXT
            );
            INSERT INTO link_check_results
                (link_id, url, checked_at, method, ok, http_status, final_url, error)
            SELECT DISTINCT ON (l.id)
                l.id, l.url, old.checked_at, old.method, old.ok,
                old.http_status, old.final_url, old.error
            FROM links l
            JOIN link_check_results_old old ON old.url = l.url
            ORDER BY l.id;
            DROP TABLE link_check_results_old;
        ELSE
            -- Fresh install.
            CREATE TABLE link_check_results (
                link_id     INTEGER PRIMARY KEY REFERENCES links(id) ON DELETE CASCADE,
                url         TEXT,
                checked_at  TEXT,
                method      TEXT,
                ok          BOOLEAN,
                http_status INTEGER,
                final_url   TEXT,
                error       TEXT
            );
        END IF;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS link_check_results_url_idx ON link_check_results (url);
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
                            "link",
                            models.OneToOneField(
                                db_column="link_id",
                                on_delete=django.db.models.deletion.CASCADE,
                                primary_key=True,
                                serialize=False,
                                to="explorer.link",
                            ),
                        ),
                        ("url", models.TextField(blank=True, null=True)),
                        ("checked_at", models.TextField(blank=True, null=True)),
                        ("method", models.TextField(blank=True, null=True)),
                        ("ok", models.BooleanField(blank=True, null=True)),
                        ("http_status", models.IntegerField(blank=True, null=True)),
                        ("final_url", models.TextField(blank=True, null=True)),
                        ("error", models.TextField(blank=True, null=True)),
                    ],
                    options={"db_table": "link_check_results"},
                ),
            ],
        ),
    ]

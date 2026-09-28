"""Convert checked_at from TEXT to TIMESTAMP WITH TIME ZONE.

Existing values are ISO 8601 strings written by datetime.isoformat(),
so Postgres can cast them directly.
"""

from django.db import migrations, models


_FORWARD = """
ALTER TABLE link_check_results
ALTER COLUMN checked_at TYPE TIMESTAMP WITH TIME ZONE
USING checked_at::TIMESTAMPTZ;
"""

_REVERSE = """
ALTER TABLE link_check_results
ALTER COLUMN checked_at TYPE TEXT
USING checked_at::TEXT;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0019_rename_collections_to_collection_pages"),
    ]

    operations = [
        migrations.RunSQL(sql=_FORWARD, reverse_sql=_REVERSE),
        migrations.AlterField(
            model_name="linkcheckresult",
            name="checked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

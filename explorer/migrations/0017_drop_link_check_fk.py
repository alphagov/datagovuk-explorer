from django.db import migrations

_UP = """
ALTER TABLE link_check_results
    DROP CONSTRAINT IF EXISTS link_check_results_link_id_fkey;
"""

# Cannot safely restore the FK after IDs may have drifted; leave as-is on rollback.
_DOWN = ""


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0016_link_check_results"),
    ]

    operations = [
        migrations.RunSQL(_UP, _DOWN),
    ]

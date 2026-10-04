from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('explorer', '0002_dataset_years'),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_datasets_harvested ON datasets(harvested)",
            reverse_sql="DROP INDEX IF EXISTS idx_datasets_harvested",
        ),
    ]

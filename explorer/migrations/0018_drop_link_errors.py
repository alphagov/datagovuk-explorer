from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0017_drop_link_check_fk"),
    ]

    operations = [
        migrations.DeleteModel(name="LinkError"),
    ]

# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_updatestatus"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesettings",
            name="services_host",
            field=models.CharField(
                blank=True,
                help_text="LAN IP or hostname for library-installed service cards",
                max_length=255,
            ),
        ),
    ]

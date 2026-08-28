# Generated manually for catalog_slug field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0003_service_host_service_logo_service_path_service_port_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="service",
            name="catalog_slug",
            field=models.CharField(
                blank=True,
                help_text="Library catalog slug when added from the app library",
                max_length=64,
            ),
        ),
    ]

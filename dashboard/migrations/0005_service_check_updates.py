from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0004_service_catalog_slug"),
    ]

    operations = [
        migrations.AddField(
            model_name="service",
            name="check_updates",
            field=models.BooleanField(
                default=True,
                help_text="Show update badge when a newer catalog release is available",
            ),
        ),
    ]

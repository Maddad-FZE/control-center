from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0012_sitesettings_cloudflare"),
    ]

    operations = [
        migrations.CreateModel(
            name="SettingsNote",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("body", models.TextField(blank=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Settings note",
                "verbose_name_plural": "Settings notes",
            },
        ),
    ]

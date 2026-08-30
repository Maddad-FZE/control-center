from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0004_librarynote"),
    ]

    operations = [
        migrations.CreateModel(
            name="TunnelRoute",
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
                ("hostname", models.CharField(max_length=255, unique=True)),
                ("catalog_slug", models.CharField(blank=True, max_length=64)),
                ("service_id", models.PositiveIntegerField(blank=True, null=True)),
                ("origin_url", models.CharField(max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Tunnel route",
                "verbose_name_plural": "Tunnel routes",
            },
        ),
    ]

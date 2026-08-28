# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="CatalogRelease",
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
                ("repo", models.CharField(max_length=128, unique=True)),
                ("latest_version", models.CharField(blank=True, max_length=64)),
                ("release_url", models.URLField(blank=True)),
                ("checked_at", models.DateTimeField(blank=True, null=True)),
                ("check_error", models.CharField(blank=True, max_length=255)),
            ],
            options={
                "verbose_name": "Catalog release",
                "verbose_name_plural": "Catalog releases",
            },
        ),
        migrations.CreateModel(
            name="InstalledService",
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
                ("slug", models.CharField(max_length=64, unique=True)),
                ("container_name", models.CharField(max_length=100)),
                ("host_port", models.PositiveIntegerField(default=0)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("installing", "Installing"),
                            ("running", "Running"),
                            ("error", "Error"),
                        ],
                        default="installing",
                        max_length=16,
                    ),
                ),
                ("error", models.TextField(blank=True)),
                ("installed_version", models.CharField(blank=True, max_length=64)),
                ("installed_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Installed service",
                "verbose_name_plural": "Installed services",
            },
        ),
    ]

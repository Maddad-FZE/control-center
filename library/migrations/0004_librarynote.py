from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0003_installedservice_managed"),
    ]

    operations = [
        migrations.CreateModel(
            name="LibraryNote",
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
                "verbose_name": "Library note",
                "verbose_name_plural": "Library notes",
            },
        ),
    ]

# Generated manually for library app

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="AddonState",
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
                ("enabled", models.BooleanField(default=True)),
            ],
            options={
                "verbose_name": "Addon state",
                "verbose_name_plural": "Addon states",
            },
        ),
    ]

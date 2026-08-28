from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0002_installedservice_catalogrelease"),
    ]

    operations = [
        migrations.AddField(
            model_name="installedservice",
            name="managed",
            field=models.BooleanField(
                default=True,
                help_text="False when detected from an existing Docker container",
            ),
        ),
        migrations.AlterField(
            model_name="installedservice",
            name="status",
            field=models.CharField(
                choices=[
                    ("installing", "Installing"),
                    ("running", "Running"),
                    ("stopped", "Stopped"),
                    ("error", "Error"),
                ],
                default="installing",
                max_length=16,
            ),
        ),
    ]

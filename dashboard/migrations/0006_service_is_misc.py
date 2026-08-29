from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0005_service_check_updates"),
    ]

    operations = [
        migrations.AddField(
            model_name="service",
            name="is_misc",
            field=models.BooleanField(
                default=False,
                help_text="Show this card in Misc as a compact bookmark instead of Apps or Tracked",
            ),
        ),
        migrations.AlterField(
            model_name="service",
            name="description",
            field=models.CharField(blank=True, max_length=512),
        ),
    ]

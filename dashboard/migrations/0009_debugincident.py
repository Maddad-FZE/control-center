import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("dashboard", "0008_service_kuma_monitor_id"),
    ]

    operations = [
        migrations.CreateModel(
            name="DebugIncident",
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
                ("incident_id", models.CharField(db_index=True, max_length=32, unique=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("queued", "Queued"),
                            ("running", "Running"),
                            ("healthy", "Healthy"),
                            ("needs_action", "Needs action"),
                            ("manual_only", "Manual only"),
                            ("failed", "Failed"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="queued",
                        max_length=16,
                    ),
                ),
                ("findings_json", models.JSONField(blank=True, default=list)),
                ("actions_json", models.JSONField(blank=True, default=list)),
                ("snapshot_json", models.JSONField(blank=True, default=dict)),
                ("report_text", models.TextField(blank=True)),
                ("cancel_requested", models.BooleanField(default=False)),
                ("repair_jobs", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="debug_incidents",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "service",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="debug_incidents",
                        to="dashboard.service",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]

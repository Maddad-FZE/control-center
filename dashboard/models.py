from django.db import models


class ServiceCategory(models.Model):
    class Layout(models.TextChoices):
        GRID = "grid", "Grid tiles"
    ROWS = "rows", "Wide cards (4-up)"

    name = models.CharField(max_length=100, unique=True)
    sort_order = models.PositiveIntegerField(default=0)
    layout = models.CharField(
        max_length=8,
        choices=Layout.choices,
        default=Layout.GRID,
    )

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "Service categories"

    def __str__(self):
        return self.name


class Service(models.Model):
    class WidgetType(models.TextChoices):
        NONE = "none", "None"
        PIHOLE = "pihole", "Pi-hole"
        SPEEDTEST = "speedtest", "Speedtest Tracker"

    category = models.ForeignKey(
        ServiceCategory, on_delete=models.CASCADE, related_name="services"
    )
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)
    href = models.URLField()
    icon = models.URLField(blank=True)
    health_check_url = models.URLField(blank=True, help_text="Leave blank to skip checks")
    is_public = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    enabled = models.BooleanField(default=True)
    widget_type = models.CharField(
        max_length=16,
        choices=WidgetType.choices,
        default=WidgetType.NONE,
    )
    widget_url = models.URLField(blank=True, help_text="Widget API base URL")
    widget_api_key = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["category__sort_order", "sort_order", "name"]

    def __str__(self):
        return self.name


class Bookmark(models.Model):
    name = models.CharField(max_length=100)
    href = models.URLField()
    icon = models.URLField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class ServiceCheck(models.Model):
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="checks")
    checked_at = models.DateTimeField(auto_now_add=True, db_index=True)
    is_up = models.BooleanField()
    response_ms = models.PositiveIntegerField(null=True, blank=True)
    error = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-checked_at"]


class Alert(models.Model):
    service = models.ForeignKey(Service, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    level = models.CharField(max_length=16, default="info")
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True)
    acknowledged = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

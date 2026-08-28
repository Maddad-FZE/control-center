from urllib.parse import urlparse

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
    href = models.URLField(blank=True)
    host = models.CharField(max_length=255, blank=True, help_text="IP or hostname")
    port = models.PositiveIntegerField(null=True, blank=True)
    path = models.CharField(max_length=255, blank=True, default="/")
    icon = models.URLField(blank=True)
    logo = models.ImageField(upload_to="service_logos/", blank=True)
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
    catalog_slug = models.CharField(
        max_length=64,
        blank=True,
        help_text="Library catalog slug when added from the app library",
    )
    check_updates = models.BooleanField(
        default=True,
        help_text="Show update badge when a newer catalog release is available",
    )

    class Meta:
        ordering = ["category__sort_order", "sort_order", "name"]

    def __str__(self):
        return self.name

    def _normalized_path(self):
        path = self.path or "/"
        if not path.startswith("/"):
            path = "/" + path
        return path

    def _base_url_from_host(self):
        if self.host and self.port:
            return f"http://{self.host}:{self.port}"
        return ""

    def _sync_from_widget_url(self):
        """Fill host/port from widget_url when the host field was left empty."""
        if self.host or not self.widget_url:
            return
        parsed = urlparse(self.widget_url)
        if parsed.hostname:
            self.host = parsed.hostname
        if parsed.port:
            self.port = parsed.port

    def build_href(self):
        base = self._base_url_from_host()
        if base:
            return f"{base}{self._normalized_path()}"
        if self.widget_url:
            parsed = urlparse(self.widget_url)
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}{self._normalized_path()}"
        return self.href

    def save(self, *args, **kwargs):
        self._sync_from_widget_url()
        base = self._base_url_from_host()
        if base:
            if (
                self.widget_type == Service.WidgetType.PIHOLE
                and self._normalized_path() == "/"
            ):
                self.path = "/admin/"
            self.href = f"{base}{self._normalized_path()}"
            self.widget_url = base
            if not self.health_check_url or "/admin" in self.health_check_url:
                self.health_check_url = f"{base}/admin/"
        else:
            built = self.build_href()
            if built:
                self.href = built
            if not self.health_check_url and self.href:
                self.health_check_url = self.href
        super().save(*args, **kwargs)

    @property
    def display_icon(self):
        if self.logo:
            return self.logo.url
        if self.icon:
            return self.icon
        if self.catalog_slug:
            from library.icons import icon_url_for_slug

            return icon_url_for_slug(self.catalog_slug)
        from library.icons import default_icon_url

        return default_icon_url()


class ServiceMetric(models.Model):
    service = models.ForeignKey(
        Service, on_delete=models.CASCADE, related_name="metrics"
    )
    label = models.CharField(max_length=64)
    json_path = models.CharField(
        max_length=128,
        help_text="Dotted path in API JSON, e.g. queries.total",
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "label"]

    def __str__(self):
        return f"{self.service.name}: {self.label}"


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

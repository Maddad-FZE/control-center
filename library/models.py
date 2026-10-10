from django.db import models


class AddonState(models.Model):
    slug = models.CharField(max_length=64, unique=True)
    enabled = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Addon state"
        verbose_name_plural = "Addon states"

    def __str__(self):
        return f"{self.slug} ({'on' if self.enabled else 'off'})"


class InstalledService(models.Model):
    class Status(models.TextChoices):
        INSTALLING = "installing", "Installing"
        RUNNING = "running", "Running"
        STOPPED = "stopped", "Stopped"
        ERROR = "error", "Error"

    slug = models.CharField(max_length=64, unique=True)
    container_name = models.CharField(max_length=100)
    host_port = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.INSTALLING,
    )
    managed = models.BooleanField(
        default=True,
        help_text="False when detected from an existing Docker container",
    )
    error = models.TextField(blank=True)
    installed_version = models.CharField(max_length=64, blank=True)
    installed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Installed service"
        verbose_name_plural = "Installed services"

    def __str__(self):
        return f"{self.slug} ({self.status})"


class CatalogRelease(models.Model):
    repo = models.CharField(max_length=128, unique=True)
    latest_version = models.CharField(max_length=64, blank=True)
    release_url = models.URLField(blank=True)
    checked_at = models.DateTimeField(null=True, blank=True)
    check_error = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "Catalog release"
        verbose_name_plural = "Catalog releases"

    def __str__(self):
        return f"{self.repo} ({self.latest_version or 'unknown'})"


class TunnelRoute(models.Model):
    hostname = models.CharField(max_length=255, unique=True)
    catalog_slug = models.CharField(max_length=64, blank=True)
    service_id = models.PositiveIntegerField(null=True, blank=True)
    origin_url = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Tunnel route"
        verbose_name_plural = "Tunnel routes"

    def __str__(self):
        return self.hostname


class LibraryNote(models.Model):
    body = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Library note"
        verbose_name_plural = "Library notes"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Library notes"


class CatalogItem(models.Model):
    slug = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=100)
    tagline = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=64)
    repo = models.CharField(max_length=128, blank=True)
    website = models.URLField(blank=True)
    icon = models.URLField(blank=True)
    default_port = models.PositiveIntegerField(default=8080)
    container_port = models.PositiveSmallIntegerField(
        default=0,
        help_text="0 = parse from compose",
    )
    path = models.CharField(max_length=255, default="/")
    widget_type = models.CharField(max_length=32, default="none")
    compose = models.TextField(blank=True)
    install_options = models.CharField(max_length=32, blank=True)
    is_builtin = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "Catalog item"
        verbose_name_plural = "Catalog items"

    def __str__(self):
        return self.name

    def to_entry(self):
        entry = {
            "slug": self.slug,
            "name": self.name,
            "tagline": self.tagline,
            "category": self.category,
            "repo": self.repo,
            "website": self.website,
            "icon": self.icon,
            "default_port": self.default_port,
            "path": self.path or "/",
            "widget_type": self.widget_type or "none",
            "compose": self.compose,
            "description": self.description,
        }
        if self.install_options:
            entry["install_options"] = self.install_options
        if self.container_port:
            entry["container_port"] = self.container_port
        return entry

from django.db import models
from django.contrib.auth.models import User


class SiteSettings(models.Model):
    title = models.CharField(max_length=120, blank=True)
    tagline = models.CharField(max_length=200, blank=True)
    logo = models.ImageField(upload_to="branding/", blank=True)
    favicon = models.FileField(upload_to="branding/", blank=True)
    weather_location = models.CharField(max_length=120, blank=True)
    weather_lat = models.FloatField(null=True, blank=True)
    weather_lon = models.FloatField(null=True, blank=True)
    crt_enabled = models.BooleanField(default=True)
    wizard_enabled = models.BooleanField(default=False)
    wizard_notify = models.BooleanField(default=True)
    services_host = models.CharField(
        max_length=255,
        blank=True,
        help_text="LAN IP or hostname for library-installed service cards",
    )

    class Meta:
        verbose_name = "Site settings"
        verbose_name_plural = "Site settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Site settings"


class UpdateStatus(models.Model):
    class InstallState(models.TextChoices):
        IDLE = "idle", "Idle"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    last_checked_at = models.DateTimeField(null=True, blank=True)
    latest_version = models.CharField(max_length=32, blank=True)
    release_url = models.URLField(blank=True)
    release_notes = models.TextField(blank=True)
    release_published_at = models.DateTimeField(null=True, blank=True)
    check_error = models.CharField(max_length=255, blank=True)
    install_state = models.CharField(
        max_length=16,
        choices=InstallState.choices,
        default=InstallState.IDLE,
    )
    install_started_at = models.DateTimeField(null=True, blank=True)
    install_finished_at = models.DateTimeField(null=True, blank=True)
    install_log = models.TextField(blank=True)
    installed_version = models.CharField(max_length=32, blank=True)
    restart_required = models.BooleanField(default=False)
    install_step = models.CharField(max_length=64, blank=True)
    install_step_index = models.PositiveSmallIntegerField(default=0)
    install_total_steps = models.PositiveSmallIntegerField(default=0)
    install_target_version = models.CharField(max_length=32, blank=True)

    class Meta:
        verbose_name = "Update status"
        verbose_name_plural = "Update status"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Update status"


class UserProfile(models.Model):
    class Theme(models.TextChoices):
        WOOD = "wood", "Wood & Orange"
        SLATE = "slate", "Cool Slate"
        TERMINAL = "terminal", "Green Terminal"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    crt_enabled = models.BooleanField(default=True)
    theme = models.CharField(max_length=16, choices=Theme.choices, default=Theme.WOOD)
    logo_url = models.URLField(blank=True, default="/static/img/logo.png")

    def __str__(self):
        return f"Profile({self.user.username})"


class AuditEvent(models.Model):
    class EventType(models.TextChoices):
        LOGIN = "login", "Login"
        LOGOUT = "logout", "Logout"
        LOGIN_FAILED = "login_failed", "Login failed"
        LOCKOUT = "lockout", "Lockout"
        ADMIN = "admin", "Admin change"
        SERVICE_DOWN = "service_down", "Service down"
        SERVICE_UP = "service_up", "Service up"
        APP = "app", "Application"

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    username = models.CharField(max_length=150, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    message = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.event_type} @ {self.created_at}"


def log_audit(event_type, request=None, user=None, message="", **metadata):
    ip = None
    username = ""
    if request is not None:
        ip = request.META.get("REMOTE_ADDR")
        if request.headers.get("X-Forwarded-For"):
            ip = request.headers.get("X-Forwarded-For").split(",")[0].strip()
    if user is not None and user.is_authenticated:
        username = user.username
    elif metadata.get("username"):
        username = metadata.pop("username")
    AuditEvent.objects.create(
        event_type=event_type,
        user=user if user and user.is_authenticated else None,
        username=username,
        ip_address=ip,
        message=message,
        metadata=metadata,
    )

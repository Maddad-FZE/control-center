from django.apps import AppConfig


class CoreConfig(AppConfig):
    default = True
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        import core.db  # noqa: F401
        import core.signals  # noqa: F401

        from core.logs import ensure_log_dirs

        ensure_log_dirs()

from .base import *  # noqa: F403,F401

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "192.168.0.40", "zaidan.home", "[::1]", "testserver"]

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

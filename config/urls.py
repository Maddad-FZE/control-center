from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    path("", include("dashboard.urls")),
    path("library/", include("library.urls")),
    path("notes/", include("apps.notes.urls")),
]


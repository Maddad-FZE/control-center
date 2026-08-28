from django.urls import path

from . import views

urlpatterns = [
    path("sw.js", views.service_worker_view, name="service_worker"),
    path("login/", views.ThemedLoginView.as_view(), name="login"),
    path("logout/", views.ThemedLogoutView.as_view(), name="logout"),
    path("setup/", views.setup_view, name="setup"),
    path("profile/", views.profile_view, name="profile"),
    path("settings/", views.settings_view, name="settings"),
    path(
        "password/change/",
        views.ThemedPasswordChangeView.as_view(),
        name="password_change",
    ),
    path("audit/", views.audit_log_view, name="audit_log"),
    path("api/updates/status/", views.api_update_status, name="api_update_status"),
    path("api/updates/check/", views.api_update_check, name="api_update_check"),
    path("api/updates/install/", views.api_update_install, name="api_update_install"),
]

from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.ThemedLoginView.as_view(), name="login"),
    path("logout/", views.ThemedLogoutView.as_view(), name="logout"),
    path("profile/", views.profile_view, name="profile"),
    path("settings/", views.settings_view, name="settings"),
    path(
        "password/change/",
        views.ThemedPasswordChangeView.as_view(),
        name="password_change",
    ),
    path("audit/", views.audit_log_view, name="audit_log"),
    path("settings/crt/", views.toggle_crt, name="toggle_crt"),
]

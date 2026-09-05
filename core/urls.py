from django.urls import path

from . import views

urlpatterns = [
    path("sw.js", views.service_worker_view, name="service_worker"),
    path("media/<path:path>", views.public_media_view, name="public_media"),
    path("login/", views.ThemedLoginView.as_view(), name="login"),
    path("login/2fa/", views.login_2fa_view, name="login_2fa"),
    path("logout/", views.ThemedLogoutView.as_view(), name="logout"),
    path("setup/", views.setup_view, name="setup"),
    path("profile/", views.profile_view, name="profile"),
    path("settings/", views.settings_view, name="settings"),
    path("settings/api/notes/", views.api_settings_notes, name="api_settings_notes"),
    path("settings/api/logs/sources/", views.api_logs_sources, name="api_logs_sources"),
    path("settings/api/logs/download/", views.api_logs_download, name="api_logs_download"),
    path("settings/api/logs/", views.api_logs, name="api_logs"),
    path("settings/api/console/ticket/", views.api_console_ticket, name="api_console_ticket"),
    path("settings/api/users/", views.api_users, name="api_users"),
    path("settings/api/users/services/", views.api_users_services, name="api_users_services"),
    path("settings/api/users/<int:user_id>/", views.api_user_detail, name="api_user_detail"),
    path(
        "settings/api/users/<int:user_id>/password/",
        views.api_user_password,
        name="api_user_password",
    ),
    path(
        "settings/api/users/<int:user_id>/2fa/reset/",
        views.api_user_2fa_reset,
        name="api_user_2fa_reset",
    ),
    path("profile/api/2fa/start/", views.api_2fa_start, name="api_2fa_start"),
    path("profile/api/2fa/confirm/", views.api_2fa_confirm, name="api_2fa_confirm"),
    path("profile/api/2fa/disable/", views.api_2fa_disable, name="api_2fa_disable"),
    path("profile/api/vault/", views.api_vault_entries, name="api_vault_entries"),
    path("profile/api/vault/services/", views.api_vault_services, name="api_vault_services"),
    path("profile/api/vault/<int:entry_id>/", views.api_vault_entry, name="api_vault_entry"),
    path(
        "profile/api/vault/<int:entry_id>/reveal/",
        views.api_vault_reveal,
        name="api_vault_reveal",
    ),
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

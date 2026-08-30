from django.urls import path

from . import views

urlpatterns = [
    path("", views.library_view, name="library"),
    path("api/addons/<slug:slug>/toggle/", views.api_addon_toggle, name="api_addon_toggle"),
    path("api/services/<slug:slug>/install/", views.api_service_install, name="api_service_install"),
    path("api/services/<slug:slug>/uninstall/", views.api_service_uninstall, name="api_service_uninstall"),
    path("api/services/<slug:slug>/status/", views.api_service_status, name="api_service_status"),
    path("api/services/<slug:slug>/restart/", views.api_service_restart, name="api_service_restart"),
    path("api/notes/", views.api_library_notes, name="api_library_notes"),
    path("api/tunnel/status/", views.api_tunnel_status, name="api_tunnel_status"),
    path("api/tunnel/link/", views.api_tunnel_link, name="api_tunnel_link"),
    path("api/tunnel/unlink/", views.api_tunnel_unlink, name="api_tunnel_unlink"),
    path("api/tunnel/publish/", views.api_tunnel_publish, name="api_tunnel_publish"),
    path("api/tunnel/unpublish/", views.api_tunnel_unpublish, name="api_tunnel_unpublish"),
]

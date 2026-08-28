from django.urls import path

from . import views

urlpatterns = [
    path("", views.library_view, name="library"),
    path("api/addons/<slug:slug>/toggle/", views.api_addon_toggle, name="api_addon_toggle"),
    path("api/services/<slug:slug>/install/", views.api_service_install, name="api_service_install"),
    path("api/services/<slug:slug>/uninstall/", views.api_service_uninstall, name="api_service_uninstall"),
    path("api/services/<slug:slug>/status/", views.api_service_status, name="api_service_status"),
]

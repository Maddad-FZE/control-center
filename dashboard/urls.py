from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("cards/new/", views.service_create_view, name="service_create"),
    path("cards/<int:service_id>/edit/", views.service_edit_view, name="service_edit"),
    path(
        "api/services/<int:service_id>/visibility/",
        views.api_service_visibility,
        name="api_service_visibility",
    ),
    path(
        "api/services/<int:service_id>/delete/",
        views.api_service_delete,
        name="api_service_delete",
    ),
    path("api/system/", views.api_system, name="api_system"),
    path("api/docker/", views.api_docker, name="api_docker"),
    path("api/health/", views.api_health, name="api_health"),
    path("api/alerts/", views.api_alerts, name="api_alerts"),
    path("api/alerts/ack/", views.api_alerts_ack, name="api_alerts_ack"),
    path("api/uptime/", views.api_uptime, name="api_uptime"),
    path("api/widgets/", views.api_widgets, name="api_widgets"),
    path("api/weather/", views.api_weather, name="api_weather"),
]

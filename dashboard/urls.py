from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("api/system/", views.api_system, name="api_system"),
    path("api/docker/", views.api_docker, name="api_docker"),
    path("api/health/", views.api_health, name="api_health"),
    path("api/alerts/", views.api_alerts, name="api_alerts"),
    path("api/alerts/ack/", views.api_alerts_ack, name="api_alerts_ack"),
    path("api/uptime/", views.api_uptime, name="api_uptime"),
    path("api/widgets/", views.api_widgets, name="api_widgets"),
    path("api/weather/", views.api_weather, name="api_weather"),
]

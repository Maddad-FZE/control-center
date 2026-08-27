from django.urls import path

from . import views_public

urlpatterns = [
    path("", views_public.public_landing, name="notes_public"),
]

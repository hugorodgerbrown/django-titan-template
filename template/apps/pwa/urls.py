"""URLs for the PWA shell. The worker and manifest live at the root for scope."""

from django.urls import path

from apps.pwa import views

app_name = "pwa"

urlpatterns = [
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("sw.js", views.service_worker, name="service_worker"),
    path("offline/", views.offline, name="offline"),
]

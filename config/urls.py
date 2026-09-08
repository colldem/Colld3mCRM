from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from contacts import views
from django.views.i18n import JavaScriptCatalog


urlpatterns = [
    path("jsi18n/", JavaScriptCatalog.as_view(), name="javascript-catalog"),
    path("i18n/", include("django.conf.urls.i18n")),
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("setup/", views.setup_admin, name="setup"),
    path("health/live", views.health_live, name="health-live"),
    path("health/ready", views.health_ready, name="health-ready"),
    path("manifest.webmanifest", views.pwa_manifest, name="pwa-manifest"),
    path("sw.js", views.pwa_service_worker, name="pwa-service-worker"),
    path("", include("contacts.urls")),
]

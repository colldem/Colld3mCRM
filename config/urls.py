from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from contacts import password_reset, views
from contacts.metrics import metrics_view
from django.views.i18n import JavaScriptCatalog


urlpatterns = []
if settings.CRM_DJANGO_ADMIN:
    # Superusers only: the CRM's own settings cover everything else, with audit.
    admin.site.has_permission = lambda request: request.user.is_active and request.user.is_superuser
    urlpatterns.append(path("admin/", admin.site.urls))

urlpatterns += [
    path("jsi18n/", JavaScriptCatalog.as_view(), name="javascript-catalog"),
    path("i18n/", include("django.conf.urls.i18n")),
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("slaptazodis/atkurti/", password_reset.password_reset_request, name="password-reset"),
    path("slaptazodis/<uidb64>/<token>/", password_reset.password_reset_set, name="password-reset-set"),
    # Entra ID (OIDC) — the views 404 unless login through Entra is enabled in Settings.
    path("oidc/", include("mozilla_django_oidc.urls")),
    path("setup/", views.setup_admin, name="setup"),
    # /health/live, /health/ready and /health/jobs: contacts.middleware.HealthProbeMiddleware.
    path("metrics", metrics_view, name="metrics"),
    path("manifest.webmanifest", views.pwa_manifest, name="pwa-manifest"),
    path("sw.js", views.pwa_service_worker, name="pwa-service-worker"),
    path("api/v1/", include("contacts.api_urls")),
    path("", include("contacts.urls")),
]

# Without these, Django serves its built-in one-line replies once DEBUG is off.
# contacts/errors.py says what each page has to answer.
handler400 = "contacts.errors.bad_request"
handler403 = "contacts.errors.permission_denied"
handler404 = "contacts.errors.page_not_found"
handler500 = "contacts.errors.server_error"

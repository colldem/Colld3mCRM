import os
import sys
from datetime import timedelta
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-before-production")
DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() == "true"
# The NAS runs with production security settings. Django's in-process test
# client does not send the proxy HTTPS header, so keep redirects disabled only
# for `manage.py test` and preserve them for every deployed request.
RUNNING_TESTS = "test" in sys.argv
ALLOWED_HOSTS = [value.strip() for value in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",") if value.strip()]
CSRF_TRUSTED_ORIGINS = [value.strip() for value in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if value.strip()]
CRM_SETUP_TOKEN = os.environ.get("CRM_SETUP_TOKEN", "")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "axes",
    "contacts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    # Must follow LocaleMiddleware: it refreshes the catalog the
    # active language will read from.
    "contacts.middleware.TranslationOverrideMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "axes.middleware.AxesMiddleware",
]
if RUNNING_TESTS:
    MIDDLEWARE.remove("whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "contacts.context_processors.reminder_count",
        "contacts.context_processors.user_profile",
        "contacts.context_processors.crm_permissions",
        "contacts.context_processors.system_settings",
        "contacts.context_processors.crm_menu",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"

if os.environ.get("DB_HOST"):
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": os.environ["DB_HOST"],
        "PORT": os.environ.get("DB_PORT", "5432"),
        "NAME": os.environ.get("DB_NAME", "crm"),
        "USER": os.environ.get("DB_USER", "crm"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "CONN_MAX_AGE": 60,
    }}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=30)
# Lock the exact (username, ip) pair, and also any single IP that keeps failing
# — the latter stops username-cycling password spraying from one host. A bare
# per-username lock is intentionally left out: on the shared tailnet it would let
# one user lock another out.
AXES_LOCKOUT_PARAMETERS = [["ip_address"], ["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AXES_HTTP_RESPONSE_CODE = 429
AXES_VERBOSE = False
LANGUAGE_CODE = "lt"
LANGUAGES = [("lt", "Lietuvių"), ("en", "English")]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Europe/Vilnius"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "runtime" / "media"
# Uploaded files live on local disk by default — that is what a single-host
# Docker install wants. Point CRM_MEDIA_BACKEND at "s3" to keep them in
# S3-compatible object storage instead, which is what more than one web replica
# (Kubernetes) needs: a pod that is rescheduled must not take the files with it.
MEDIA_BACKEND = os.environ.get("CRM_MEDIA_BACKEND", "filesystem").strip().lower()
if MEDIA_BACKEND == "s3":
    _default_storage = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": os.environ["CRM_S3_BUCKET"],
            "endpoint_url": os.environ.get("CRM_S3_ENDPOINT") or None,
            "region_name": os.environ.get("CRM_S3_REGION", "") or None,
            "access_key": os.environ.get("CRM_S3_ACCESS_KEY") or None,
            "secret_key": os.environ.get("CRM_S3_SECRET_KEY") or None,
            # Uploads are private: they are served through the CRM, which checks
            # who may see the record the file hangs off.
            "default_acl": None,
            "querystring_auth": True,
            "file_overwrite": False,
            "addressing_style": os.environ.get("CRM_S3_ADDRESSING", "virtual"),
        },
    }
else:
    _default_storage = {"BACKEND": "django.core.files.storage.FileSystemStorage"}

STORAGES = {
    "default": _default_storage,
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG or RUNNING_TESTS
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
# Cap a single multipart request: file count and total non-file payload.
DATA_UPLOAD_MAX_NUMBER_FILES = 25
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "contacts:list"
LOGOUT_REDIRECT_URL = "login"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
# Idle timeout: the session expires this long after the last request.
SESSION_COOKIE_AGE = int(os.environ.get("DJANGO_SESSION_IDLE_MINUTES", "480")) * 60
SESSION_SAVE_EVERY_REQUEST = True
FORCE_HTTPS = os.environ.get("DJANGO_FORCE_HTTPS", "false").lower() == "true"
SESSION_COOKIE_SECURE = FORCE_HTTPS and not RUNNING_TESTS
CSRF_COOKIE_SECURE = FORCE_HTTPS and not RUNNING_TESTS
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_SSL_REDIRECT = FORCE_HTTPS and not RUNNING_TESTS
SECURE_REDIRECT_EXEMPT = [r"^health/"]
SECURE_HSTS_SECONDS = 0 if DEBUG else int(os.environ.get("DJANGO_HSTS_SECONDS", "86400"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG

# Integration secrets (SMTP / IMAP passwords, Entra client secret) are entered in
# the Settings UI and stored encrypted with this key. Keep it in .env only.
CRM_SECRETS_KEY = os.environ.get("CRM_SECRETS_KEY", "")
if RUNNING_TESTS and not CRM_SECRETS_KEY:
    from cryptography.fernet import Fernet

    os.environ["CRM_SECRETS_KEY"] = CRM_SECRETS_KEY = Fernet.generate_key().decode()

# Email / IMAP / Entra: the Settings UI is the primary source. These environment
# values are only a fallback for deployments that prefer to configure them here.
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "true").lower() == "true"
EMAIL_USE_SSL = os.environ.get("EMAIL_USE_SSL", "false").lower() == "true"
EMAIL_TIMEOUT = 20
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "crm@localhost")
# Fallback backend for any send that does not go through contacts.notifications
# (which builds its own SMTP connection from the effective config).
if RUNNING_TESTS:
    EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
elif EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
# Absolute base for links inside emails / .ics (no request object in the worker).
CRM_BASE_URL = os.environ.get("CRM_BASE_URL", "https://%s" % (ALLOWED_HOSTS[0] if ALLOWED_HOSTS else "localhost"))

# Deployment tier. Anything but "production" is an isolated copy — typically a
# staging clone restored from a production dump, holding real personal data.
# Such a tier must not reach the outside world, so contacts.integrations and
# contacts.webhooks force SMTP, IMAP, Entra and webhook delivery off no matter
# what the restored database says. This lives in the environment on purpose:
# refreshing the data cannot switch it back on.
CRM_ENVIRONMENT = (os.environ.get("CRM_ENVIRONMENT") or "production").strip().lower()
CRM_ISOLATED = CRM_ENVIRONMENT != "production"

IMAP_HOST = os.environ.get("IMAP_HOST", "")
IMAP_PORT = int(os.environ.get("IMAP_PORT", "993"))
IMAP_USER = os.environ.get("IMAP_USER", "")
IMAP_PASSWORD = os.environ.get("IMAP_PASSWORD", "")
IMAP_FOLDER = os.environ.get("IMAP_FOLDER", "INBOX")

OIDC_ENV_ENABLED = os.environ.get("OIDC_ENABLED", "false").lower() == "true"
OIDC_RP_CLIENT_ID = os.environ.get("OIDC_RP_CLIENT_ID", "")
OIDC_RP_CLIENT_SECRET = os.environ.get("OIDC_RP_CLIENT_SECRET", "")
OIDC_TENANT_ID = os.environ.get("OIDC_TENANT_ID", "")
OIDC_CREATE_USERS = os.environ.get("OIDC_CREATE_USERS", "false").lower() == "true"

# OIDC plumbing is always loaded; whether login through Entra is actually offered
# and accepted is decided per request from the database (see contacts/oidc.py).
INSTALLED_APPS.append("mozilla_django_oidc")
AUTHENTICATION_BACKENDS.append("contacts.oidc.EntraOIDCBackend")
OIDC_AUTHENTICATE_CLASS = "contacts.oidc.EntraRequestView"
OIDC_CALLBACK_CLASS = "contacts.oidc.EntraCallbackView"
OIDC_USERNAME_ALGO = "contacts.oidc.username_from_claims"
OIDC_RP_SIGN_ALGO = "RS256"
OIDC_RP_SCOPES = "openid email profile"
LOGIN_REDIRECT_URL = "contacts:list"
LOGOUT_REDIRECT_URL = "login"

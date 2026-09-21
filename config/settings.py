import os
import sys
from datetime import timedelta
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

# The NAS runs with production security settings. Django's in-process test
# client does not send the proxy HTTPS header, so keep redirects disabled only
# for `manage.py test` and preserve them for every deployed request.
RUNNING_TESTS = "test" in sys.argv
# Fail safe: with a real database (DB_HOST) DEBUG is off unless asked for, and a
# missing secret key stops the process instead of signing sessions with a
# publicly known one. A local SQLite checkout keeps the developer defaults.
_DEV_DEFAULT_KEY = "dev-only-change-before-production"
DEBUG = os.environ.get("DJANGO_DEBUG", "false" if os.environ.get("DB_HOST") else "true").lower() == "true"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", _DEV_DEFAULT_KEY)
if SECRET_KEY == _DEV_DEFAULT_KEY and os.environ.get("DB_HOST") and not RUNNING_TESTS:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured("DJANGO_SECRET_KEY is not set: refusing to start with the development key.")
# Django's own /admin/ edits records outside the audit trail and CRM permissions,
# so it is off unless explicitly enabled, and then for superusers only.
CRM_DJANGO_ADMIN = os.environ.get("CRM_DJANGO_ADMIN", "false").lower() == "true"
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

# Apps installed beside the CRM — today the Regitra integration, which fills the
# record card's middle column (contacts/record_blocks.py). Comma separated, so a
# deployment switches one on without patching this file.
INSTALLED_APPS += [name.strip() for name in os.environ.get("CRM_EXTRA_APPS", "").split(",") if name.strip()]

MIDDLEWARE = [
    # First, so every log line of the request carries its id (contacts/observability.py).
    "contacts.observability.RequestIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Content-Security-Policy (nonce) and Permissions-Policy.
    "contacts.middleware.SecurityHeadersMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    # Must follow LocaleMiddleware: it refreshes the catalog the
    # active language will read from.
    "contacts.middleware.TranslationOverrideMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Re-checks directory sessions with the identity provider (contacts/oidc.py).
    "contacts.oidc.DirectorySessionRefresh",
    # The "Skaitytojas" role: refuses editing pages and shared-data writes.
    "contacts.middleware.ReadOnlyRoleMiddleware",
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
        "contacts.context_processors.csp",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"

if os.environ.get("DB_ENGINE") == "oracle":
    # Not a supported production target: used by the Oracle compatibility check in
    # CI (docs/ORACLE.md). NAME is the service name; the driver is python-oracledb.
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.oracle",
        # Easy Connect "host:port/service" in NAME: Django reads HOST/PORT as a SID.
        "HOST": "",
        "PORT": "",
        "NAME": "%s:%s/%s" % (os.environ["DB_HOST"], os.environ.get("DB_PORT", "1521"),
                              os.environ.get("DB_NAME", "FREEPDB1")),
        "USER": os.environ.get("DB_USER", "system"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "TEST": {"USER": "crm_test", "PASSWORD": os.environ.get("DB_PASSWORD", ""), "TBLSPACE": "crm_test_tbls",
                 "TBLSPACE_TMP": "crm_test_tmp"},
    }}
elif os.environ.get("DB_HOST"):
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
    # ModelBackend that refuses local passwords in SSO-only mode (break-glass excepted).
    "contacts.oidc.LocalAccountBackend",
]
# Logs go to stdout: one JSON object per line for a SIEM ("json", the default
# outside DEBUG) or plain text ("text"). See contacts/observability.py.
CRM_LOG_FORMAT = os.environ.get("CRM_LOG_FORMAT", "text" if DEBUG else "json").lower()
CRM_LOG_LEVEL = os.environ.get("CRM_LOG_LEVEL", "INFO").upper()
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_id": {"()": "contacts.observability.RequestIdFilter"}},
    "formatters": {
        "json": {"()": "contacts.observability.JsonFormatter"},
        "text": {"format": "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"},
    },
    "handlers": {
        "stdout": {"class": "logging.StreamHandler", "stream": "ext://sys.stdout", "filters": ["request_id"],
                   "formatter": "json" if CRM_LOG_FORMAT == "json" else "text"},
        "null": {"class": "logging.NullHandler"},
    },
    "root": {"handlers": ["null" if RUNNING_TESTS else "stdout"], "level": CRM_LOG_LEVEL},
    "loggers": {
        "django": {"level": "INFO", "propagate": True},
        # Suppressed 4xx noise is still visible at WARNING; 5xx at ERROR.
        "django.request": {"level": "WARNING", "propagate": True},
        "django.security": {"level": "INFO", "propagate": True},
        "crm.security": {"level": "INFO", "propagate": True},
        "axes": {"level": "WARNING", "propagate": True},
    },
}

# Send the Content-Security-Policy as report-only (for checking a new setup).
CRM_CSP_REPORT_ONLY = os.environ.get("CRM_CSP_REPORT_ONLY", "false").lower() == "true"

# Reverse proxies (CIDR list) whose X-Forwarded-For is believed for the client
# address used by the audit trail and the sign-in lockout. Empty: connection address.
import ipaddress  # noqa: E402

CRM_TRUSTED_PROXIES = os.environ.get("CRM_TRUSTED_PROXIES", "").strip()
CRM_TRUSTED_PROXY_NETWORKS = tuple(
    ipaddress.ip_network(item.strip(), strict=False) for item in CRM_TRUSTED_PROXIES.split(",") if item.strip())

# Bearer token for /metrics (Prometheus); empty = endpoint off.
CRM_METRICS_TOKEN = os.environ.get("CRM_METRICS_TOKEN", "").strip()

# Malware scanning of uploads through clamd (contacts/antivirus.py); empty host = off.
CRM_CLAMAV_HOST = os.environ.get("CRM_CLAMAV_HOST", "").strip()
CRM_CLAMAV_PORT = int(os.environ.get("CRM_CLAMAV_PORT", "3310"))
CRM_CLAMAV_TIMEOUT = int(os.environ.get("CRM_CLAMAV_TIMEOUT", "30"))
# Refuse uploads while the scanner is unreachable (true) or accept them unscanned.
CRM_CLAMAV_REQUIRED = os.environ.get("CRM_CLAMAV_REQUIRED", "true").lower() == "true"

# JSON API requests allowed per token per minute (0 = unlimited).
CRM_API_RATE_LIMIT = int(os.environ.get("CRM_API_RATE_LIMIT", "120"))
# Usernames allowed to sign in with a local password while SSO-only mode is on.
# Empty: active superusers only.
CRM_BREAK_GLASS_USERS = [name.strip().lower() for name in os.environ.get("CRM_BREAK_GLASS_USERS", "").split(",") if name.strip()]
# A reset link is a key to an account, and this one travels by e-mail: Django's
# three-day default is far longer than anyone needs to read their inbox.
PASSWORD_RESET_TIMEOUT = int(os.environ.get("CRM_PASSWORD_RESET_TIMEOUT", str(60 * 60)))
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
# Lock out by the real client address, not by the reverse proxy's (contacts/audit.py).
AXES_CLIENT_IP_CALLABLE = "contacts.audit.client_ip"
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
# Django's own CSRF page explains cookies and referers to somebody who was
# only filling in a form; ours says what to do about it.
CSRF_FAILURE_VIEW = "contacts.errors.csrf_failure"

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
# A refused directory sign-in lands on the login page, where the reason is shown.
LOGIN_REDIRECT_URL_FAILURE = "/login/"
LOGIN_REDIRECT_URL = "contacts:list"
LOGOUT_REDIRECT_URL = "login"

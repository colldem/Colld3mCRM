"""Effective integration configuration.

Each accessor merges the database settings (entered in the Settings UI) with the
matching ``.env`` fallback, so the rest of the app never reads ``os.environ`` or
``django.conf.settings`` for SMTP / IMAP / Entra directly. The database wins when
a value is filled in; otherwise the environment value is used.
"""
from dataclasses import dataclass

from django.conf import settings as dj

from .crypto import decrypt
from .models import SystemSettings


@dataclass
class EmailConfig:
    host: str
    port: int
    user: str
    password: str
    use_tls: bool
    use_ssl: bool
    from_email: str
    enabled: bool

    @property
    def configured(self):
        return bool(self.host)


@dataclass
class ImapConfig:
    host: str
    port: int
    user: str
    password: str
    folder: str
    enabled: bool

    @property
    def active(self):
        return bool(self.enabled and self.host)


@dataclass
class OIDCConfig:
    enabled: bool
    tenant_id: str
    client_id: str
    client_secret: str
    create_users: bool

    @property
    def authority(self):
        return "https://login.microsoftonline.com/%s/v2.0" % (self.tenant_id or "common")

    @property
    def authorization_endpoint(self):
        return self.authority + "/authorize"

    @property
    def token_endpoint(self):
        return self.authority + "/token"

    @property
    def user_endpoint(self):
        return self.authority.replace("/v2.0", "") + "/openid/userinfo"

    @property
    def jwks_endpoint(self):
        return self.authority + "/keys"

    @property
    def usable(self):
        """True when login through Entra should be offered and accepted."""
        return bool(self.enabled and self.client_id and self.client_secret)


def _load(system):
    return system or SystemSettings.load()


def _isolated():
    """True on a non-production tier (see ``CRM_ISOLATED`` in settings).

    A staging clone is restored from a production dump, so its database carries
    the real SMTP, IMAP and Entra credentials. Every accessor below returns an
    inert config there, which is what keeps the clone from mailing real
    contacts. Gating at construction means no caller can bypass it.
    """
    return getattr(dj, "CRM_ISOLATED", False)


def email_config(system=None):
    if _isolated():
        return EmailConfig(host="", port=0, user="", password="", use_tls=False,
                           use_ssl=False, from_email=dj.DEFAULT_FROM_EMAIL, enabled=False)
    system = _load(system)
    host = system.email_host or dj.EMAIL_HOST
    from_db = bool(system.email_host)
    return EmailConfig(
        host=host,
        port=system.email_port if from_db else dj.EMAIL_PORT,
        user=system.email_host_user or dj.EMAIL_HOST_USER,
        password=decrypt(system.email_host_password) or (dj.EMAIL_HOST_PASSWORD if not from_db else ""),
        use_tls=system.email_use_tls if from_db else dj.EMAIL_USE_TLS,
        use_ssl=system.email_use_ssl if from_db else dj.EMAIL_USE_SSL,
        from_email=system.email_from or dj.DEFAULT_FROM_EMAIL,
        enabled=system.notifications_enabled,
    )


def imap_config(system=None):
    if _isolated():
        return ImapConfig(host="", port=0, user="", password="", folder="INBOX", enabled=False)
    system = _load(system)
    host = system.imap_host or dj.IMAP_HOST
    from_db = bool(system.imap_host)
    return ImapConfig(
        host=host,
        port=system.imap_port if from_db else dj.IMAP_PORT,
        user=system.imap_user or dj.IMAP_USER,
        password=decrypt(system.imap_password) or (dj.IMAP_PASSWORD if not from_db else ""),
        folder=system.imap_folder or dj.IMAP_FOLDER or "INBOX",
        enabled=system.imap_enabled or (bool(dj.IMAP_HOST) and not from_db),
    )


def oidc_config(system=None):
    if _isolated():
        return OIDCConfig(enabled=False, tenant_id="", client_id="", client_secret="", create_users=False)
    system = _load(system)
    from_db = bool(system.oidc_client_id)
    return OIDCConfig(
        enabled=system.oidc_enabled or (dj.OIDC_ENV_ENABLED and not from_db),
        tenant_id=system.oidc_tenant_id or dj.OIDC_TENANT_ID,
        client_id=system.oidc_client_id or dj.OIDC_RP_CLIENT_ID,
        client_secret=decrypt(system.oidc_client_secret) or (dj.OIDC_RP_CLIENT_SECRET if not from_db else ""),
        create_users=system.oidc_create_users or (dj.OIDC_CREATE_USERS and not from_db),
    )


def site_base_url(system=None):
    system = _load(system)
    return (system.site_base_url or dj.CRM_BASE_URL or "").rstrip("/")

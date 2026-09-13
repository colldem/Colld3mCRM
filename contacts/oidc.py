"""Organisation sign-in through OpenID Connect: Microsoft Entra ID or AD FS (G5).

Whether Entra login is offered and accepted is decided per request from the
database (Settings -> Prisijungimas), so an admin can turn it on, paste the
tenant / client id / secret, and it works without a container restart. The
endpoints, client id and secret are resolved through :func:`_resolve` instead of
static Django settings.

Local username/password login stays as the fallback. An Entra identity is only
linked to an existing, active CRM user by email/UPN — unless "create users" is
turned on, in which case a fresh user is provisioned with no usable local
password.

On top of the library's signature and nonce checks, every ID token is checked
for issuer, audience, expiry and (Entra) tenant. With directory group sync on,
roles and teams follow the user's AD groups — see contacts/directory.py.
"""
import time

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import SuspiciousOperation
from django.http import Http404
from mozilla_django_oidc import views as oidc_views
from mozilla_django_oidc.auth import OIDCAuthenticationBackend
from mozilla_django_oidc.utils import import_from_settings

from . import directory
from .integrations import oidc_config


def tr_disabled():
    from django.utils.translation import gettext

    return gettext("Jūsų CRM paskyra išjungta. Kreipkitės į administratorių.")


def username_from_claims(email, claims=None):
    """Wired in as ``OIDC_USERNAME_ALGO`` (settings.py).

    mozilla-django-oidc inspects this function's signature to decide how to
    call it: a single-argument callable is treated as the *old* style and
    called with just the email string, a two-argument one gets
    ``(email, claims)`` — the modern convention, and the one this must match
    or ``get_username()`` hands it a plain string where a dict is expected.
    """
    claims = claims or {}
    return (claims.get("preferred_username") or email or claims.get("upn") or "").lower()[:150]


def _resolve(attr, *args):
    """mozilla-django-oidc setting lookup, database first."""
    cfg = oidc_config()
    dynamic = {
        "OIDC_RP_CLIENT_ID": cfg.client_id,
        "OIDC_RP_CLIENT_SECRET": cfg.client_secret,
        "OIDC_OP_AUTHORIZATION_ENDPOINT": cfg.authorization_endpoint,
        "OIDC_OP_TOKEN_ENDPOINT": cfg.token_endpoint,
        "OIDC_OP_USER_ENDPOINT": cfg.user_endpoint,
        "OIDC_OP_JWKS_ENDPOINT": cfg.jwks_endpoint,
    }
    if attr in dynamic and dynamic[attr]:
        return dynamic[attr]
    return import_from_settings(attr, *args)


CLOCK_SKEW_SECONDS = 120


def validate_id_token_claims(payload, config, now=None):
    """Raise SuspiciousOperation unless the token was issued for this CRM."""
    now = time.time() if now is None else now
    audience = payload.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    if config.client_id not in audiences:
        raise SuspiciousOperation("ID token audience mismatch")
    try:
        expires = float(payload.get("exp"))
    except (TypeError, ValueError):
        raise SuspiciousOperation("ID token has no expiry") from None
    if expires + CLOCK_SKEW_SECONDS < now:
        raise SuspiciousOperation("ID token expired")
    issuer = str(payload.get("iss") or "").rstrip("/")
    if config.is_entra:
        tenant = str(payload.get("tid") or "")
        if not tenant or issuer != "https://login.microsoftonline.com/%s/v2.0" % tenant:
            raise SuspiciousOperation("ID token issuer mismatch")
        configured = config.tenant_id.strip().lower()
        # A tenant configured as a GUID must match exactly; a domain name was
        # already pinned by using that tenant's own token endpoint.
        if len(configured) == 36 and configured.count("-") == 4 and tenant.lower() != configured:
            raise SuspiciousOperation("ID token tenant mismatch")
    elif issuer != config.expected_issuer:
        raise SuspiciousOperation("ID token issuer mismatch")
    return payload


class EntraOIDCBackend(OIDCAuthenticationBackend):
    @staticmethod
    def get_settings(attr, *args):
        return _resolve(attr, *args)

    def verify_token(self, token, **kwargs):
        return validate_id_token_claims(super().verify_token(token, **kwargs), oidc_config())

    def get_userinfo(self, access_token, id_token, payload):
        """Claims from the verified ID token, completed by the userinfo endpoint.

        Groups, tenant and object id live only in the ID token (neither Entra's
        nor AD FS's userinfo returns them), so the token's claims take precedence.
        """
        userinfo = {}
        if oidc_config().user_endpoint:
            try:
                userinfo = super().get_userinfo(access_token, id_token, payload) or {}
            except Exception:  # nosec B110
                userinfo = {}
        return {**userinfo, **(payload or {})}

    def _refuse(self, message):
        request = getattr(self, "request", None)
        if request is not None:
            messages.error(request, message)
        return None

    def get_or_create_user(self, access_token, id_token, payload):
        try:
            user = super().get_or_create_user(access_token, id_token, payload)
            if user is None:
                return None
            claims = self.get_userinfo(access_token, id_token, payload)
            config = oidc_config()
            if config.sync_groups:
                directory.apply(user, claims, config, request=getattr(self, "request", None))
            else:
                from .models import UserProfile

                subject = directory.check_subject(user, claims, config)
                if subject:
                    UserProfile.objects.filter(user=user, directory_subject="").update(directory_subject=subject)
            return user
        except directory.DirectoryAccessDenied as denied:
            return self._refuse(str(denied))

    def _email(self, claims):
        return (claims.get("email") or claims.get("preferred_username") or claims.get("upn") or "").lower()

    def filter_users_by_claims(self, claims):
        subject = directory.subject_of(claims, oidc_config())
        if subject:
            linked = self.UserModel.objects.filter(crm_profile__directory_subject=subject, is_active=True)
            if linked.exists():
                return linked
        email = self._email(claims)
        if not email:
            return self.UserModel.objects.none()
        return self.UserModel.objects.filter(email__iexact=email, is_active=True)

    def verify_claims(self, claims):
        return bool(self._email(claims))

    def create_user(self, claims):
        config = oidc_config()
        if not config.create_users:
            return None  # link-only: unknown identities are rejected
        from .models import UserProfile

        email = self._email(claims)
        username = username_from_claims(email, claims)
        if get_user_model().objects.filter(email__iexact=email).exists() or \
                get_user_model().objects.filter(username__iexact=username).exists():
            raise directory.DirectoryAccessDenied(tr_disabled())
        if config.sync_groups:
            denied = directory.evaluate(claims, config).denied
            if denied:
                raise directory.DirectoryAccessDenied(denied)

        user = super().create_user(claims)
        user.first_name = (claims.get("given_name") or "")[:150]
        user.last_name = (claims.get("family_name") or "")[:150]
        user.set_unusable_password()
        user.save()
        UserProfile.objects.get_or_create(user=user)
        return user

    def update_user(self, user, claims):
        changed = []
        for field, key in (("first_name", "given_name"), ("last_name", "family_name")):
            value = (claims.get(key) or "")[:150]
            if value and getattr(user, field) != value:
                setattr(user, field, value)
                changed.append(field)
        if changed:
            user.save(update_fields=changed)
        return user


class _EntraViewMixin:
    @staticmethod
    def get_settings(attr, *args):
        return _resolve(attr, *args)

    def dispatch(self, request, *args, **kwargs):
        if not oidc_config().usable:
            raise Http404
        return super().dispatch(request, *args, **kwargs)


class EntraRequestView(_EntraViewMixin, oidc_views.OIDCAuthenticationRequestView):
    pass


class EntraCallbackView(_EntraViewMixin, oidc_views.OIDCAuthenticationCallbackView):
    pass

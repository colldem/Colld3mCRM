"""Microsoft Entra ID (OpenID Connect) login (G5).

Whether Entra login is offered and accepted is decided per request from the
database (Settings -> Prisijungimas), so an admin can turn it on, paste the
tenant / client id / secret, and it works without a container restart. The
endpoints, client id and secret are resolved through :func:`_resolve` instead of
static Django settings.

Local username/password login stays as the fallback. An Entra identity is only
linked to an existing, active CRM user by email/UPN — unless "create users" is
turned on, in which case a fresh user is provisioned with no usable local
password.
"""
from django.http import Http404
from mozilla_django_oidc import views as oidc_views
from mozilla_django_oidc.auth import OIDCAuthenticationBackend
from mozilla_django_oidc.utils import import_from_settings

from .integrations import oidc_config


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


class EntraOIDCBackend(OIDCAuthenticationBackend):
    @staticmethod
    def get_settings(attr, *args):
        return _resolve(attr, *args)

    def _email(self, claims):
        return (claims.get("email") or claims.get("preferred_username") or claims.get("upn") or "").lower()

    def filter_users_by_claims(self, claims):
        email = self._email(claims)
        if not email:
            return self.UserModel.objects.none()
        return self.UserModel.objects.filter(email__iexact=email, is_active=True)

    def verify_claims(self, claims):
        return bool(self._email(claims))

    def create_user(self, claims):
        if not oidc_config().create_users:
            return None  # link-only: unknown identities are rejected
        from .models import UserProfile

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

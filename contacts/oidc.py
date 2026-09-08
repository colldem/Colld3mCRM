"""Microsoft Entra ID (OpenID Connect) login (G5).

Local username/password login stays as the fallback. An Entra identity is only
linked to an existing, active CRM user by email/UPN — unless OIDC_CREATE_USERS
is turned on, in which case a fresh user is provisioned with the default role
(member, all-records visibility) and no usable local password.
"""
from django.conf import settings


def username_from_claims(claims):
    return (claims.get("preferred_username") or claims.get("email") or claims.get("upn") or "").lower()[:150]


try:  # the dependency is only installed / imported when OIDC is enabled
    from mozilla_django_oidc.auth import OIDCAuthenticationBackend

    class EntraOIDCBackend(OIDCAuthenticationBackend):
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
            if not settings.OIDC_CREATE_USERS:
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
except ImportError:  # pragma: no cover
    EntraOIDCBackend = None

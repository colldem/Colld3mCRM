"""Role helpers. `is_superuser` always counts as an administrator."""
from .models import UserProfile


def role_of(user):
    if not getattr(user, "is_authenticated", False):
        return None
    if user.is_superuser:
        return UserProfile.ROLE_ADMIN
    profile = getattr(user, "crm_profile", None)
    if profile and profile.role:
        return profile.role
    return UserProfile.ROLE_ADMIN if user.is_staff else UserProfile.ROLE_MEMBER


def is_admin(user):
    return role_of(user) == UserProfile.ROLE_ADMIN


def sees_all_records(user):
    return role_of(user) in (UserProfile.ROLE_ADMIN, UserProfile.ROLE_MEMBER)


def active_admin_ids():
    from django.contrib.auth import get_user_model

    ids = set()
    for user in get_user_model().objects.filter(is_active=True).select_related("crm_profile"):
        if is_admin(user):
            ids.add(user.pk)
    return ids

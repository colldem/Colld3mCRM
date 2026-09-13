"""Account lifecycle: switching off accounts nobody uses.

An account that has not signed in for ``SystemSettings.deactivate_inactive_days``
is deactivated by the worker (``manage.py deactivate_inactive_users``). Its API
tokens stop working with it. Break-glass accounts are never touched. A directory
user switched off this way is let back in by the next sign-in that the directory
still allows (see contacts/oidc.py); an administrator's manual switch-off is final.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import AuditLog, SystemSettings, UserProfile

INACTIVITY = "inactivity"
MANUAL = "manual"


def inactive_users(days, now=None):
    now = now or timezone.now()
    cutoff = now - timedelta(days=days)
    return get_user_model().objects.filter(is_active=True).filter(
        Q(last_login__lt=cutoff) | Q(last_login__isnull=True, date_joined__lt=cutoff))


def deactivate_inactive(now=None):
    """Switch off unused accounts; returns the usernames that were switched off."""
    from .audit import log as audit_log
    from .oidc import is_break_glass

    days = SystemSettings.load().deactivate_inactive_days
    if not days:
        return []
    done = []
    for user in inactive_users(days, now):
        if is_break_glass(user):
            continue
        user.is_active = False
        user.save(update_fields=["is_active"])
        UserProfile.objects.update_or_create(user=user, defaults={"deactivated_reason": INACTIVITY})
        audit_log(AuditLog.UPDATE, target=user, target_type="user", field=_("Būsena"), old=_("aktyvus"), new=_("išjungtas"),
                  detail={"reason": INACTIVITY, "days": days})
        done.append(user.get_username())
    return done


def reactivate_after_inactivity(user, request=None):
    """Undo an automatic switch-off; False when it was switched off by hand."""
    from .audit import log as audit_log

    profile = UserProfile.objects.filter(user=user).first()
    if user.is_active or not profile or profile.deactivated_reason != INACTIVITY:
        return False
    user.is_active = True
    user.save(update_fields=["is_active"])
    profile.deactivated_reason = ""
    profile.save(update_fields=["deactivated_reason", "updated_at"])
    audit_log(AuditLog.UPDATE, request=request, actor=user, target=user, target_type="user", field=_("Būsena"),
              old=_("išjungtas"), new=_("aktyvus"), detail={"reason": "directory sign-in after inactivity"})
    return True

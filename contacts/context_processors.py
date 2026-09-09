from django.conf import settings as dj_settings
from django.db.models import F, Q
from django.utils import timezone

from .reminder_queries import pending_reminders
from .models import SystemSettings, UserProfile


def reminder_count(request):
    if not request.user.is_authenticated:
        return {"active_reminder_count": 0, "active_reminders_menu": []}
    now = timezone.now()
    pending = pending_reminders(request.user)
    # A task someone else handed you surfaces in the bell straight away, even if
    # it is not due yet, until you have opened it.
    handed_to_me = Q(assigned_to=request.user, read_at__isnull=True) & ~Q(assigned_to=F("created_by"))
    active = pending.filter(Q(due_at__lte=now) | handed_to_me)
    return {"active_reminder_count": active.filter(read_at__isnull=True).count(),
            "active_reminders_menu": active,
            "scheduled_reminders_menu": pending.filter(due_at__gt=now).exclude(handed_to_me)}


def user_profile(request):
    if not request.user.is_authenticated:
        return {"crm_user_profile": None}
    return {"crm_user_profile": UserProfile.objects.filter(user=request.user).first()}


def system_settings(request):
    from .integrations import oidc_config

    system = SystemSettings.load()
    return {"date_format": system.date_format, "datetime_format": system.datetime_format,
            "oidc_enabled": oidc_config(system).usable,
            # Names the tier in the top banner so a clone holding real data is
            # never mistaken for production.
            "crm_environment": dj_settings.CRM_ENVIRONMENT,
            "crm_isolated": dj_settings.CRM_ISOLATED}


def crm_permissions(request):
    from .permissions import CAPABILITY_KEYS, has_capability, is_admin

    if not request.user.is_authenticated:
        return {"is_crm_admin": False, "crm_caps": {}}
    return {
        "is_crm_admin": is_admin(request.user),
        "crm_caps": {key: has_capability(request.user, key) for key in CAPABILITY_KEYS},
    }

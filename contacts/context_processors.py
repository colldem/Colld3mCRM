from django.utils import timezone

from .reminder_queries import pending_reminders
from .models import SystemSettings, UserProfile


def reminder_count(request):
    if not request.user.is_authenticated:
        return {"active_reminder_count": 0, "active_reminders_menu": []}
    now = timezone.now()
    pending = pending_reminders(request.user)
    reminders = pending.filter(due_at__lte=now)
    return {"active_reminder_count": reminders.filter(read_at__isnull=True).count(),
            "active_reminders_menu": reminders, "scheduled_reminders_menu": pending.filter(due_at__gt=now)}


def user_profile(request):
    if not request.user.is_authenticated:
        return {"crm_user_profile": None}
    return {"crm_user_profile": UserProfile.objects.filter(user=request.user).first()}


def system_settings(request):
    system = SystemSettings.load()
    return {"date_format": system.date_format, "datetime_format": system.datetime_format}


def crm_permissions(request):
    from .permissions import CAPABILITY_KEYS, has_capability, is_admin

    if not request.user.is_authenticated:
        return {"is_crm_admin": False, "crm_caps": {}}
    return {
        "is_crm_admin": is_admin(request.user),
        "crm_caps": {key: has_capability(request.user, key) for key in CAPABILITY_KEYS},
    }
